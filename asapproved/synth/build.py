"""Render masters to disk, each with a sidecar describing exactly what is in it.

The sidecar is the point. `<id>.master.json` carries the region boxes, the
per-frame visibility of each region, the warning text as rendered, and the file
hash. Variants are built from it, ground truth is derived from it, and SAM's
masks are scored against it.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from asapproved.canonical import sha256_file
from asapproved.ffmpeg import run_ffmpeg
from asapproved.synth.render import Layout, RenderedFrame, draw_frame
from asapproved.synth.specs import MasterSpec

__all__ = [
    "render_master_frame",
    "build_master",
    "write_video",
    "master_sidecar",
    "compliant_layout",
]

# Gap left between the warning box and the platform's reserved zone, as a
# fraction of frame height. Not zero: a warning touching the very edge of the
# caption block would be compliant by our own arithmetic and obviously risky in
# real life.
SAFE_MARGIN = 0.03


def compliant_layout(spec: MasterSpec) -> Layout:
    """Place the warning OUTSIDE the placement's reserved UI zone.

    Found while rendering: the default position (78% down the frame) sits inside
    the Reels caption block, which reserves the bottom 35% — 40% once the
    creative carries a disclaimer, and a prescribed risk warning is one. Every
    Reels master was therefore breaching R12 as the approved baseline.

    A baseline that fails the rule it is used to measure makes the measurement
    meaningless, so position is derived from the placement rather than fixed.
    """
    from asapproved.vision.overlays import get_spec

    placement = spec.placement
    if placement == "reels":
        placement = "reels_with_disclaimer"  # every master carries a warning box

    zone = get_spec(placement)
    return Layout(
        safe_top=zone.top + SAFE_MARGIN,
        safe_bottom=1.0 - zone.bottom - SAFE_MARGIN,
        warning_top=None,  # bottom-align within the band the placement leaves
    )


def render_master_frame(
    spec: MasterSpec, frame_index: int = 0, layout: Layout | None = None
) -> RenderedFrame:
    """One frame of a master. Masters are compliant in every frame, by design."""
    w, h = spec.size
    phase = (frame_index / max(1, spec.total_frames)) * 2.0
    return draw_frame(
        brand=spec.brand,
        width=w,
        height=h,
        headline=spec.headline,
        trigger=spec.trigger,
        apr_line=spec.apr_line,
        warning_text=spec.warning_text,
        body_text=spec.body_text,
        apr_label=spec.apr_label,
        layout=layout or compliant_layout(spec),
        phase=phase,
    )


def write_video(frames: list[Image.Image], out_path: Path, fps: int) -> Path:
    """Encode frames to H.264 MP4 via ffmpeg.

    Written as PNGs to a temp dir then encoded in one pass, rather than piped:
    a pipe failure mid-stream leaves a truncated file that looks valid, and a
    silently corrupt master would poison every measurement taken against it.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = frames[0].size
    if w % 2 or h % 2:
        raise ValueError(
            f"{out_path.name}: H.264/yuv420p needs even dimensions, got {w}x{h}. "
            "Even-ify frames and their masks together (see synth.variants._even) so the "
            "ground-truth boxes stay aligned with the pixels."
        )
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for i, frame in enumerate(frames):
            frame.save(tmpdir / f"{i:05d}.png")
        run_ffmpeg(
            [
                "-framerate",
                str(fps),
                "-i",
                str(tmpdir / "%05d.png"),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(out_path),
            ]
        )
    return out_path


def master_sidecar(spec: MasterSpec, rendered: RenderedFrame, path: Path) -> dict:
    """Everything a downstream step needs to know about this master."""
    total = spec.total_frames
    return {
        "id": spec.id,
        "source": "SIMULATED",
        "brand": spec.brand.name,
        "kind": spec.kind,
        "size": list(spec.size),
        "fps": spec.fps if spec.kind == "video" else None,
        "duration_s": spec.duration_s if spec.kind == "video" else None,
        "total_frames": total,
        "placement": spec.placement,
        "investment_type": spec.investment_type,
        "trigger_text": spec.trigger,
        "apr_text": spec.apr_line,
        "warning_text": spec.warning_text,
        "regions": {k: [int(v) for v in b] for k, b in sorted(rendered.regions.items())},
        # Compliant master: every region is on screen for every frame. R4's
        # ground-truth ratio is therefore 1.0 here, and variants reduce it.
        "visible_frames": {k: [[0, total - 1]] for k in sorted(rendered.regions)},
        "audio": {
            "vo_speaks_trigger": spec.vo_speaks_trigger if spec.kind == "video" else None,
            "vo_speaks_apr": spec.vo_speaks_apr if spec.kind == "video" else None,
            "track": None,  # filled in at USER INPUT 3.1
        },
        "file": path.name,
        "sha256": sha256_file(path),
        "compliant_by_construction": True,
    }


def build_master(spec: MasterSpec, out_dir: Path, *, progress=None) -> tuple[Path, Path]:
    """Render one master plus its sidecar. Returns (asset_path, sidecar_path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_path = out_dir / spec.filename

    if spec.kind == "still":
        rendered = render_master_frame(spec)
        rendered.image.save(asset_path)
    else:
        frames = []
        first: RenderedFrame | None = None
        for i in range(spec.total_frames):
            rendered = render_master_frame(spec, i)
            if first is None:
                first = rendered
            frames.append(rendered.image)
            if progress:
                progress(i + 1, spec.total_frames)
        write_video(frames, asset_path, spec.fps)
        rendered = first  # regions are identical across frames of a master

    sidecar_path = out_dir / f"{spec.id}.master.json"
    sidecar = master_sidecar(spec, rendered, asset_path)
    sidecar_path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8")
    return asset_path, sidecar_path


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
