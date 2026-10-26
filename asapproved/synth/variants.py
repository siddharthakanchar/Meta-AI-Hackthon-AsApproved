"""Build variants and derive their ground truth by measurement, not assertion.

The important choice here: region boxes and per-frame visibility in a variant are
obtained by pushing each region's MASK through the very same transform that made
the variant, then taking its bounding box. A crop that removes the warning
removes it from the mask too; a pan that slides the APR off screen slides the
mask off screen on the same frame.

The alternative — declaring "this transform hides the warning from frame 30" —
would be a second, hand-maintained description of what the code does, and the two
would drift. Here the label cannot disagree with the pixels, because it is
computed from them.

Where a transform also declares expected visibility, the two are cross-checked
and a mismatch is an error. That is a genuine test of the generator rather than a
restatement of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from asapproved.canonical import sha256_file
from asapproved.synth.build import compliant_layout, write_video
from asapproved.synth.derive import derive_violations
from asapproved.synth.render import Layout, RenderedFrame, draw_frame
from asapproved.synth.specs import MasterSpec
from asapproved.synth.transforms import FrameCtx, Transform, VariantPlan

__all__ = ["build_variant", "VariantResult", "ranges_from_flags"]

MIN_VISIBLE_PIXELS = 24  # below this a region is a sliver, not "on screen"


@dataclass(frozen=True)
class VariantResult:
    asset_path: Path
    label: dict


def ranges_from_flags(flags: list[bool]) -> list[list[int]]:
    """Compress per-frame booleans into inclusive [start, end] ranges."""
    ranges: list[list[int]] = []
    start: int | None = None
    for i, v in enumerate(flags):
        if v and start is None:
            start = i
        elif not v and start is not None:
            ranges.append([start, i - 1])
            start = None
    if start is not None:
        ranges.append([start, len(flags) - 1])
    return ranges


def _even(img: np.ndarray) -> np.ndarray:
    """Trim to even width/height.

    H.264 with yuv420p cannot encode odd dimensions, and the crop transforms
    produce them (691x1241 from a margin trim). Applied to frames AND masks in
    the same place, so a one-pixel trim can never desync the ground-truth boxes
    from the pixels they describe.
    """
    h, w = img.shape[:2]
    return img[: h - (h % 2), : w - (w % 2)]


def _mask_image(box: tuple[int, int, int, int], size: tuple[int, int]) -> np.ndarray:
    w, h = size
    mask = np.zeros((h, w, 3), dtype=np.uint8)
    x, y, bw, bh = box
    mask[y : y + bh, x : x + bw] = 255
    return mask


def _bbox_of_mask(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    gray = mask[..., 0] if mask.ndim == 3 else mask
    ys, xs = np.nonzero(gray > 127)
    if ys.size < MIN_VISIBLE_PIXELS:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def variant_layout(spec: MasterSpec, transform: Transform) -> tuple[Layout, str]:
    """The layout and warning text this variant is drawn with.

    Exposed so ground truth can be derived from what was DRAWN rather than from
    what was intended — see synth/derive.py.
    """
    base_layout = compliant_layout(spec)
    layout = transform.layout_fn(spec, base_layout) if transform.layout_fn else base_layout
    warning_text = transform.text_fn(spec) if transform.text_fn else spec.warning_text
    return layout, warning_text


def _render_variant_frame(
    spec: MasterSpec, transform: Transform, frame_index: int
) -> RenderedFrame:
    """Render the variant's base frame, applying any layout/text lever."""
    layout, warning_text = variant_layout(spec, transform)
    w, h = spec.size
    phase = (frame_index / max(1, spec.total_frames)) * 2.0
    return draw_frame(
        brand=spec.brand,
        width=w,
        height=h,
        headline=spec.headline,
        trigger=spec.trigger,
        apr_line=spec.apr_line,
        warning_text=warning_text,
        body_text=spec.body_text,
        apr_label=spec.apr_label,
        layout=layout,
        phase=phase,
    )


def build_variant(plan: VariantPlan, out_dir: Path, *, progress=None) -> VariantResult:
    spec, transform = plan.master, plan.transform
    out_dir.mkdir(parents=True, exist_ok=True)
    total = spec.total_frames
    tracked = [r for r in ("warning", spec.apr_label, "trigger") if r]

    base = _render_variant_frame(spec, transform, 0)
    base_regions = base.regions
    ctx = FrameCtx(spec=spec, regions=dict(base_regions), size=spec.size)

    # --- frames + per-frame region visibility -------------------------
    visible: dict[str, list[bool]] = {r: [] for r in tracked}
    final_boxes: dict[str, tuple[int, int, int, int] | None] = {}
    frames: list[Image.Image] = []

    for i in range(total):
        # Video backgrounds drift, so each frame is rendered fresh — the same as
        # the master, which keeps the pair alignable for C3.
        rendered = base if spec.kind == "still" else _render_variant_frame(spec, transform, i)
        bgr = rendered.to_bgr()
        if transform.frame_fn is not None:
            bgr = _even(transform.frame_fn(bgr, i, total, ctx))
        frames.append(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))

        # Only re-mask every frame when the transform's geometry actually varies
        # with time. For a fixed crop the answer is the same on frame 1 and frame
        # 374, and masking 375 times would cost minutes across the set for an
        # identical result.
        if i == 0 or transform.per_frame:
            for region in tracked:
                box = rendered.regions.get(region)
                if box is None:
                    visible[region].append(False)
                    final_boxes.setdefault(region, None)
                    continue
                mask = _mask_image(box, spec.size)
                if transform.frame_fn is not None:
                    mask = _even(transform.frame_fn(mask, i, total, ctx))
                moved = _bbox_of_mask(mask)
                visible[region].append(moved is not None)
                if moved is not None:
                    final_boxes[region] = moved
                else:
                    final_boxes.setdefault(region, None)
        else:
            for region in tracked:
                visible[region].append(visible[region][0])

        if progress:
            progress(i + 1, total)

    # --- write the asset ----------------------------------------------
    if spec.kind == "still":
        asset_path = out_dir / f"{plan.variant_id}.png"
        frames[0].save(asset_path)
    else:
        asset_path = out_dir / f"{plan.variant_id}.mp4"
        write_video(frames, asset_path, spec.fps)

    # --- ground truth ---------------------------------------------------
    visible_frames = {r: ranges_from_flags(v) for r, v in visible.items()}
    visible_ratio_bp = {
        r: int(round(10_000 * sum(v) / total)) if total else 0 for r, v in visible.items()
    }

    _cross_check(plan, visible_frames)
    _cross_check_text(
        plan, transform.text_fn(spec) if transform.text_fn else spec.warning_text
    )

    layout, warning_text = variant_layout(spec, transform)
    derived = (
        []
        if transform.benign
        else derive_violations(
            spec,
            transform,
            layout,
            {k: v for k, v in final_boxes.items() if v},
            warning_text,
            visible_ratio_bp,
            {k: (v is not None) for k, v in final_boxes.items()},
            rendered_regions=dict(base_regions),
        )
    )

    label = {
        "variant_id": plan.variant_id,
        "master_id": spec.id,
        "source": "SIMULATED",
        "transform": transform.name,
        "enhancement": transform.enhancement,
        "description": transform.description,
        "benign": transform.benign,
        # Every rule this variant actually breaks, derived from what was drawn.
        # The transform's own declaration is kept alongside so a reader can see
        # what was intended versus what resulted.
        "violated_rules": derived,
        "intended_rules": list(transform.rules),
        "touched_regions": list(transform.regions),
        "requires_audio": transform.requires_audio,
        "notes": transform.notes,
        "kind": spec.kind,
        "size": list(spec.size),
        "fps": spec.fps if spec.kind == "video" else None,
        "total_frames": total,
        "placement": spec.placement,
        "investment_type": spec.investment_type,
        "warning_text": transform.text_fn(spec) if transform.text_fn else spec.warning_text,
        "master_regions": {k: [int(x) for x in v] for k, v in sorted(base_regions.items())},
        "regions": {
            k: ([int(x) for x in v] if v else None) for k, v in sorted(final_boxes.items())
        },
        "visible_frames": visible_frames,
        "visible_ratio_bp": visible_ratio_bp,
        "file": asset_path.name,
        "sha256": sha256_file(asset_path),
    }
    return VariantResult(asset_path=asset_path, label=label)


def _cross_check(plan: VariantPlan, computed: dict[str, list[list[int]]]) -> None:
    """A transform's declared visibility must match what the pixels did.

    This is the generator testing itself: `visibility_fn` is written by hand from
    intent, `computed` comes from pushing masks through the real transform. If
    they disagree, one of them is wrong and the labels cannot be trusted.
    """
    fn = plan.transform.visibility_fn
    if fn is None:
        return
    declared = fn(plan.master)
    for region, expected in declared.items():
        actual = computed.get(region)
        if actual is None:
            continue
        if not expected and actual:
            raise AssertionError(
                f"{plan.variant_id}: transform declares '{region}' never visible, "
                f"but masks say it is visible for {actual}"
            )
        if expected and not actual:
            raise AssertionError(
                f"{plan.variant_id}: transform declares '{region}' visible for {expected}, "
                "but masks say it never appears"
            )


def write_labels(labels: list[dict], path: Path) -> Path:
    """Write the frozen label set, with a hash over its canonical form."""
    from asapproved.canonical import sha256_obj

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "dataset": "VariantBench-UK",
        "source": "SIMULATED",
        "rulebook_version": "uk_v1",
        "count": len(labels),
        "violations": sum(1 for v in labels if not v["benign"]),
        "benign": sum(1 for v in labels if v["benign"]),
        "labels": sorted(labels, key=lambda v: v["variant_id"]),
    }
    doc["labels_sha256"] = sha256_obj(doc["labels"])
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _cross_check_text(plan: VariantPlan, warning_text: str) -> None:
    """A variant labelled R11 must actually differ from the prescribed wording.

    Caught a real defect: the replace-based rewrite was a no-op on the
    long-term-asset-fund warning, so that variant claimed an R11 violation while
    being byte-identical to a compliant master. The benchmark would have scored
    the detector WRONG for correctly passing it — the most expensive kind of
    label bug, because it looks like a detector failure.
    """
    if "R11" not in plan.transform.rules:
        return
    itype = plan.master.investment_type
    if not itype:
        raise AssertionError(f"{plan.variant_id}: R11 seeded on a non-investment master")

    from asapproved.synth.specs import prescribed_text
    from asapproved.text_norm import same_prescribed_text

    if same_prescribed_text(warning_text, prescribed_text(itype)):
        raise AssertionError(
            f"{plan.variant_id}: labelled R11 (wording altered) but the warning text is "
            "identical to the prescribed wording"
        )
