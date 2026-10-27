"""Derive EVERY rule a variant actually breaks, not just the one it was built for.

The problem this fixes. Each transform declares the rule it was designed to
trigger, and that was treated as the whole ground truth. But a transform that
shrinks the warning also moves it — possibly into the platform's caption zone —
and necessarily changes the claim region it sits in. Those further breaches are
real. Scoring them as false positives punished the detector for being right, and
dragged B2's per-rule precision to 14–29% on exactly the rules it handles best.

**Why this is not the detector grading its own homework.** Nothing here looks at
pixels or calls the rules engine. It reads what the generator *drew*: the RGB
values it chose, the font sizes it set, the box coordinates it placed, and the
placement zone those coordinates fall in. Contrast is the WCAG formula applied
to two known colours, not a measurement of an image. Occlusion is rectangle
intersection against a published percentage, not a detection. If the detector
had a bug, these labels would still be right — which is the whole point.

Rules that genuinely need observation (R9 spoken parity, R2 settings drift) are
not derived here and keep their declared labels.
"""

from __future__ import annotations

import numpy as np

from asapproved.measure import contrast_ratio, relative_luminance
from asapproved.synth.render import Layout
from asapproved.synth.specs import MasterSpec, prescribed_text
from asapproved.text_norm import same_prescribed_text

__all__ = ["derive_violations", "R1_TAU_BP", "CONTRAST_MIN_X100", "VISIBILITY_MIN_BP"]

# These mirror the rulebook. Kept as named constants so a reader can see that the
# ground truth uses the same thresholds the rules do — if they ever diverge, the
# benchmark is measuring something other than the rulebook.
R1_TAU_BP = 200
CONTRAST_MIN_X100 = 450
VISIBILITY_MIN_BP = 9800
R7_TOLERANCE = 0.95


def _wcag_contrast_x100(bg: tuple[int, int, int], ink: tuple[int, int, int]) -> int:
    """Contrast between two KNOWN colours. Arithmetic, not image analysis."""
    lum_bg = float(relative_luminance(np.array(bg, dtype=np.float64)))
    lum_ink = float(relative_luminance(np.array(ink, dtype=np.float64)))
    return int(round(contrast_ratio(lum_bg, lum_ink) * 100))


def _overlay_bottom(spec: MasterSpec) -> float:
    from asapproved.vision.overlays import get_spec

    placement = "reels_with_disclaimer" if spec.placement == "reels" else spec.placement
    try:
        return get_spec(placement).bottom
    except KeyError:
        return 0.0


def _overlay_left(spec: MasterSpec) -> float:
    from asapproved.vision.overlays import get_spec

    placement = "reels_with_disclaimer" if spec.placement == "reels" else spec.placement
    try:
        return get_spec(placement).left
    except KeyError:
        return 0.0


def _overlay_right(spec: MasterSpec) -> float:
    from asapproved.vision.overlays import get_spec

    placement = "reels_with_disclaimer" if spec.placement == "reels" else spec.placement
    try:
        return get_spec(placement).right
    except KeyError:
        return 0.0


def _overlay_top(spec: MasterSpec) -> float:
    from asapproved.vision.overlays import get_spec

    placement = "reels_with_disclaimer" if spec.placement == "reels" else spec.placement
    try:
        return get_spec(placement).top
    except KeyError:
        return 0.0


def derive_violations(
    spec: MasterSpec,
    transform,
    layout: Layout,
    regions: dict[str, tuple[int, int, int, int]],
    warning_text: str,
    visible_ratio_bp: dict[str, int],
    region_present: dict[str, bool],
    rendered_regions: dict[str, tuple[int, int, int, int]] | None = None,
) -> list[str]:
    """Every rule this variant actually breaks, derived from what was drawn."""
    broken: set[str] = set()
    w_img, h_img = spec.size

    warning_box = regions.get("warning")
    warning_present = region_present.get("warning", warning_box is not None)

    # --- R3: the warning is gone or clipped ---------------------------
    if not warning_present or warning_box is None:
        broken.add("R3")
    else:
        x, y, bw, bh = warning_box
        if x < 0 or y < 0 or x + bw > w_img or y + bh > h_img:
            broken.add("R3")

    # --- R1: a claim region was materially changed --------------------
    # By construction: a violating transform that touches a claim region changes
    # it materially. Benign transforms leave claim regions alone by design, which
    # is what makes them benign.
    claim_regions = {"warning", "apr", "risk_note", "trigger"}
    if not transform.benign and (set(transform.regions) & claim_regions):
        broken.add("R1")
    if "R3" in broken and not transform.benign:
        broken.add("R1")  # removing the warning necessarily changes its region

    # --- R5: border, bold, underline ----------------------------------
    if warning_present and (not layout.warning_border or not layout.warning_underline):
        broken.add("R5")

    # --- R6: contrast between the two colours we chose ----------------
    if warning_present:
        bg = layout.warning_bg or (255, 255, 255)
        ink = layout.warning_ink or (10, 10, 10)
        if _wcag_contrast_x100(bg, ink) < CONTRAST_MIN_X100:
            broken.add("R6")

    # --- R7: warning type size against body type size -----------------
    # Both are set by the renderer from the same scale, so the ratio is exactly
    # layout.warning_scale — no measurement needed.
    # Body presence comes from what the renderer DREW, not from the tracked
    # regions — those only ever hold warning, APR and trigger, so "body" was
    # never in them and R7 could never be derived. Every correct R7 detection
    # was therefore scored as a false positive.
    drew_body = "body" in (rendered_regions or {})
    if warning_present and drew_body and layout.warning_scale < R7_TOLERANCE:
        broken.add("R7")

    # --- R8: APR prominence against its trigger -----------------------
    if spec.is_credit:
        apr_vis = visible_ratio_bp.get("apr")
        trg_vis = visible_ratio_bp.get("trigger")
        apr_missing = not region_present.get("apr", True)
        apr_smaller = layout.apr_scale < 1.0
        apr_briefer = (
            apr_vis is not None and trg_vis is not None and apr_vis < trg_vis
        )
        if apr_missing or apr_smaller or apr_briefer:
            broken.add("R8")

    # --- R4: on screen throughout (video only) ------------------------
    if spec.kind == "video":
        vis = visible_ratio_bp.get("warning")
        if vis is not None and vis < VISIBILITY_MIN_BP:
            broken.add("R4")

    # --- R10: cost-of-credit figures with no representative example ---
    if spec.is_credit and not layout.show_warning:
        broken.add("R10")

    # --- R11: prescribed wording altered ------------------------------
    if (
        spec.investment_type
        and warning_present
        and not same_prescribed_text(warning_text, prescribed_text(spec.investment_type))
    ):
        broken.add("R11")

    # --- R12: inside the placement's reserved UI zone -----------------
    # "Warning OR APR" — checking only the warning was a label gap: on an
    # investment master the risk line is the APR-equivalent region, and an
    # expansion that pushed it under the caption block was a correct detection
    # that ground truth refused to credit.
    bottom = _overlay_bottom(spec)
    top = _overlay_top(spec)
    if bottom > 0 or top > 0:
        zone_top_px = top * h_img
        zone_bottom_px = (1.0 - bottom) * h_img
        for label in ("warning", spec.apr_label):
            box = regions.get(label)
            if box is None or not region_present.get(label, True):
                continue
            x, y, bw, bh = box
            # A region that runs off the frame is CLIPPED, not occluded. R12 is
            # about the platform's own chrome sitting on top of the creative, so
            # an APR that has slid out of frame belongs to R8 and R3, not here.
            # Counting it as R12 made ground truth claim a breach of a rule the
            # variant does not actually breach.
            # Deliberately NOT excluding regions that touch the frame edge.
            # Tried that, to stop an APR which had slid out of frame being
            # labelled R12 for the sliver left inside the side band — and it
            # stripped R12 from two variants where a region pushed PARTLY off
            # frame still had its remaining portion under the caption block.
            # That occlusion is real. A region can be both clipped and
            # occluded, and discarding the whole region because one edge
            # touches throws away the half that R12 is actually about.

            # Left and right bands too. The detector enforces all four, so
            # omitting the side bands made ground truth a DIFFERENT rule from
            # the one under test, and the mismatch hid real detector error.
            left_px = _overlay_left(spec) * w_img
            right_px = (1.0 - _overlay_right(spec)) * w_img
            if (
                y < zone_top_px
                or (y + bh) > zone_bottom_px
                or x < left_px
                or (x + bw) > right_px
            ):
                broken.add("R12")
                break

    # Rules that need observation rather than knowledge of what we drew keep
    # their declared labels: R9 depends on a voiceover we have not recorded, and
    # R2 compares live API settings against a manifest.
    for rule in transform.rules:
        if rule in {"R2", "R9"}:
            broken.add(rule)

    return sorted(broken, key=lambda r: int(r[1:]))
