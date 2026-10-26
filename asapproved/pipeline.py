"""End-to-end check of one variant against its approved master.

    master + variant -> align -> diff -> locate regions -> measure -> rules decide

Everything here is deterministic and keyless. Model-derived inputs (SAM masks,
Spark claim extraction, Voice Transcribe) are OPTIONAL: when they are absent the
pipeline falls back to a deterministic equivalent where an honest one exists, and
leaves the input unset where it does not — so the affected rules report
`inconclusive` rather than inventing an answer.

What is deliberately NOT done: nothing in this file reads the variant's label
file. The labels are the answer key for the benchmark; a detector that consults
them measures only its own agreement with itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from asapproved.canonical import sha256_file
from asapproved.measure import measure_region, measure_track
from asapproved.rules.engine import Context, Finding, evaluate, summarise
from asapproved.vision.align import Alignment, align_to_master
from asapproved.vision.diff import DiffResult, changed_in_region, diff_pair
from asapproved.vision.ocr import OcrResult, read_text, text_in_box
from asapproved.vision.overlays import occlusion
from asapproved.vision.track import RegionTrack, region_template, track_region

__all__ = ["CheckResult", "check_variant", "load_master", "MasterRef", "sample_frames"]

# Video is sampled rather than tracked frame by frame: 25fps x 15s x 3 regions is
# 1,125 template matches per variant, minutes per clip across the set. At 5fps the
# visibility ratio resolves to about 1.3 percentage points, finer than any
# threshold in the rulebook (R4's is 98%). The rate is recorded on every result so
# the resolution limit travels with the number rather than being folded away.
TARGET_SAMPLE_FPS = 5


@dataclass(frozen=True)
class MasterRef:
    id: str
    path: Path
    sidecar: dict[str, Any]

    @property
    def regions(self) -> dict[str, list[int]]:
        return self.sidecar.get("regions", {})

    @property
    def is_video(self) -> bool:
        return self.sidecar.get("kind") == "video"

    @property
    def placement(self) -> str | None:
        return self.sidecar.get("placement")

    @property
    def investment_type(self) -> str | None:
        return self.sidecar.get("investment_type")

    @property
    def apr_label(self) -> str:
        return "apr" if "apr" in self.regions else "risk_note"


def load_master(master_id: str, masters_dir: Path) -> MasterRef:
    sidecar_path = masters_dir / f"{master_id}.master.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    return MasterRef(id=master_id, path=masters_dir / sidecar["file"], sidecar=sidecar)


def sample_frames(path: Path, target_fps: int = TARGET_SAMPLE_FPS):
    """Return (frames, source_fps, stride). A still yields one frame."""
    path = Path(path)
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"could not read image: {path}")
        return [img], 0.0, 1

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"could not open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    stride = max(1, int(round(fps / target_fps)))

    frames: list[np.ndarray] = []
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % stride == 0:
            frames.append(frame)
        index += 1
    cap.release()
    if not frames:
        raise ValueError(f"no frames decoded from {path}")
    return frames, float(fps), stride


@dataclass
class CheckResult:
    variant_id: str
    master_id: str
    findings: list[Finding]
    summary: dict[str, Any]
    context: Context
    diff: DiffResult | None = None
    alignment: Alignment | None = None
    tracks: dict[str, RegionTrack] = field(default_factory=dict)
    region_source: str = "template_ncc"
    text_source: str = "ocr"
    sampled_fps: int = TARGET_SAMPLE_FPS
    frame_count: int = 1
    variant_sha256: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return any(f.blocking for f in self.findings)

    @property
    def failed_rules(self) -> list[str]:
        return self.summary["failed_rules"]

    def to_record(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "master_id": self.master_id,
            "variant_sha256": self.variant_sha256,
            "region_source": self.region_source,
            "text_source": self.text_source,
            "sampled_fps": self.sampled_fps,
            "frame_count": self.frame_count,
            "summary": self.summary,
            "findings": [f.to_record() for f in self.findings],
            "notes": self.notes,
        }


def _region_dict(m, text_height: int | None = None) -> dict[str, Any]:
    """Flatten a RegionMeasurement into the shape the rules read."""
    return {
        "present": m.present,
        "bbox": list(m.bbox) if m.bbox else None,
        "contrast_x100": m.contrast_x100,
        "border_present": m.border_present,
        # Bold and underline cannot be detected reliably enough from pixels to
        # assert either way (V14), so they stay unset and R5 reports them as
        # inconclusive rather than passing or failing on a guess.
        "bold_present": None,
        "underline_present": None,
        "clipped": m.clipped,
        "height_bp": m.height_bp,
        "hd_lines": m.hd_lines,
        "text_height": text_height,
    }


def _mask_from_box(box, shape) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=bool)
    x, y, w, h = box
    mask[max(0, y) : y + h, max(0, x) : x + w] = True
    return mask


def _placement_key(placement: str | None) -> str | None:
    if placement is None:
        return None
    return "reels_with_disclaimer" if placement == "reels" else placement


def _median_text_height(ocr: OcrResult, box) -> int | None:
    if not ocr.available:
        return None
    return text_in_box(ocr, tuple(box)).median_height()


def check_variant(
    variant_path,
    master: MasterRef,
    *,
    live_settings: dict[str, str] | None = None,
    manifest_settings: dict[str, str] | None = None,
    trigger_spoken: bool | None = None,
    apr_spoken: bool | None = None,
) -> CheckResult:
    """Run the full deterministic pipeline on one variant."""
    variant_path = Path(variant_path)
    notes: list[str] = []

    master_frames, _, _ = sample_frames(master.path)
    master_frame = master_frames[0]
    variant_frames, src_fps, stride = sample_frames(variant_path)
    variant_frame = variant_frames[0]

    alignment = align_to_master(master_frame, variant_frame)
    diff = diff_pair(master_frame, variant_frame, alignment)
    if not alignment.ok:
        notes.append(f"alignment degraded: {alignment.reason}")

    watched = [
        label for label in ("warning", master.apr_label, "trigger") if label in master.regions
    ]

    tracks: dict[str, RegionTrack] = {}
    for label in watched:
        template = region_template(master_frame, tuple(master.regions[label]), alignment)
        if template is None:
            notes.append(f"region '{label}' too small to track")
            continue
        tracks[label] = track_region(template, variant_frames, label)

    master_ocr = read_text(master_frame)
    variant_ocr = read_text(variant_frame)
    text_source = "ocr" if variant_ocr.available else "none"
    if not variant_ocr.available:
        notes.append("OCR unavailable: text-dependent rules report inconclusive")

    master_regions: dict[str, dict[str, Any]] = {}
    variant_regions: dict[str, dict[str, Any]] = {}
    changed_bp: dict[str, int] = {}
    occluded: dict[str, int] = {}
    occlusion_caveats: list[str] = []
    visible_bp: dict[str, int] = {}
    longest_gap: dict[str, int] = {}

    for label in watched:
        m_box = tuple(master.regions[label])
        m_mask = _mask_from_box(m_box, master_frame.shape)
        m_meas = measure_region(master_frame, m_mask, label)
        master_regions[label] = _region_dict(m_meas, _median_text_height(master_ocr, m_box))

        changed_bp[label] = changed_in_region(diff, m_mask, label).fraction_bp

        track = tracks.get(label)
        v_box = track.first_box() if track else None
        if v_box is None:
            variant_regions[label] = {"present": False, "bbox": None}
            if master.is_video:
                visible_bp[label] = 0
                longest_gap[label] = len(variant_frames) * stride
            continue

        v_mask = _mask_from_box(v_box, variant_frame.shape)
        v_meas = measure_region(
            variant_frame, v_mask, label, placement=_placement_key(master.placement)
        )
        variant_regions[label] = _region_dict(v_meas, _median_text_height(variant_ocr, v_box))

        if master.placement:
            occ = occlusion(v_mask, _placement_key(master.placement))
            occluded[label] = occ.occluded_pixels
            if occ.caveat and occ.caveat not in occlusion_caveats:
                occlusion_caveats.append(occ.caveat)

        if master.is_video and track:
            t = measure_track(track.visible, max(1.0, src_fps / stride), label)
            visible_bp[label] = t.visible_ratio_bp
            longest_gap[label] = t.longest_gap_frames * stride

    if "body" in master.regions:
        b_height = _median_text_height(variant_ocr, tuple(master.regions["body"]))
        variant_regions["body"] = {"present": b_height is not None, "text_height": b_height}

    warning_text = None
    warning_box = (variant_regions.get("warning") or {}).get("bbox")
    if warning_box:
        warning_text = text_in_box(variant_ocr, tuple(warning_box)).text() or None

    ctx = Context(
        variant_id=variant_path.stem,
        master_id=master.id,
        is_video=master.is_video,
        fps=int(src_fps) if src_fps else None,
        placement=master.placement,
        investment_type=master.investment_type,
        alignment_ok=alignment.ok,
        alignment_note=alignment.reason,
        changed_in_region_bp=changed_bp,
        master_regions=master_regions,
        variant_regions=variant_regions,
        visible_ratio_bp=visible_bp,
        longest_gap_frames=longest_gap,
        occluded_pixels=occluded,
        occlusion_caveats=occlusion_caveats,
        warning_text_variant=warning_text,
        warning_text_source=text_source if text_source == "ocr" else "exact",
        trigger_spoken=trigger_spoken,
        apr_spoken=apr_spoken,
        manifest_settings=manifest_settings or {},
        live_settings=live_settings or {},
        warning_label="warning",
        apr_label=master.apr_label,
    )

    findings = evaluate(ctx)
    return CheckResult(
        variant_id=variant_path.stem,
        master_id=master.id,
        findings=findings,
        summary=summarise(findings),
        context=ctx,
        diff=diff,
        alignment=alignment,
        tracks=tracks,
        text_source=text_source,
        sampled_fps=TARGET_SAMPLE_FPS,
        frame_count=len(variant_frames),
        variant_sha256=sha256_file(variant_path),
        notes=notes,
    )
