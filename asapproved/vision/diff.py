"""C3 part 2 — what actually changed between master and variant.

SSIM map over the aligned pair, thresholded into changed regions, then the part
that matters for R1: the intersection of "changed" with "this is a claim or a
warning". A background swap that leaves the APR box untouched is a benign edit;
the same amount of change *inside* the warning is a re-approval trigger. The
difference is the intersection, not the magnitude.

Why SSIM rather than absolute pixel difference: a brightness or contrast shift
moves every pixel value while changing no content, and an absolute diff flags the
whole frame. SSIM is comparatively insensitive to that and sensitive to structural
change — which is the thing the FCA cares about.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from asapproved.vision.align import Alignment, to_gray, warp_to_master

__all__ = ["DiffResult", "RegionChange", "diff_pair", "changed_in_region"]

# SSIM below this counts as structurally changed. 0.90 is deliberately permissive:
# JPEG/encoder noise on re-rendered previews sits comfortably above it, so this
# threshold separates "re-encoded" from "redrawn" rather than chasing exactness.
# Tuned against VariantBench-UK benign edits in Phase 6; reported with the results.
SSIM_CHANGED_BELOW = 0.90

# Drop specks smaller than this (fraction of frame area) — they are compression
# artefacts, not edits.
MIN_REGION_AREA_FRACTION = 0.0002


@dataclass(frozen=True)
class RegionChange:
    """Changed area measured against one labelled region (warning box, APR, ...).

    Ratios are basis points (1/10000) so they survive the evidence chain intact
    (`canonical.assert_no_floats`).
    """

    label: str
    region_pixels: int
    changed_pixels: int
    fraction_bp: int

    def exceeds_bp(self, threshold_bp: int) -> bool:
        return self.fraction_bp > threshold_bp


@dataclass(frozen=True)
class DiffResult:
    ssim_score: float
    ssim_map: np.ndarray
    changed_mask: np.ndarray
    boxes: list[tuple[int, int, int, int]]  # (x, y, w, h) in master coordinates
    changed_fraction_bp: int
    alignment_ok: bool
    alignment_method: str
    note: str

    @property
    def trustworthy(self) -> bool:
        """False when the geometry could not be established — R1/R3 must not fire."""
        return self.alignment_ok


def diff_pair(
    master: np.ndarray,
    variant: np.ndarray,
    alignment: Alignment | None = None,
    *,
    ssim_threshold: float = SSIM_CHANGED_BELOW,
) -> DiffResult:
    """Compare a variant to its master in master coordinates."""
    from asapproved.vision.align import align_to_master

    if alignment is None:
        alignment = align_to_master(master, variant)

    warped = warp_to_master(variant, alignment)
    mg = to_gray(master)
    vg = to_gray(warped)

    score, ssim_map = structural_similarity(mg, vg, full=True)

    changed = (ssim_map < ssim_threshold).astype(np.uint8)

    # A warp leaves black border where the variant has no data (a crop). That is
    # genuinely "missing content", but it is also structurally different from an
    # edit, so it is kept and reported rather than silently masked out: a crop that
    # removes the warning is precisely what R3 exists to catch.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, kernel)
    changed = cv2.morphologyEx(changed, cv2.MORPH_CLOSE, kernel)

    h, w = mg.shape[:2]
    min_area = max(1, int(MIN_REGION_AREA_FRACTION * h * w))

    boxes: list[tuple[int, int, int, int]] = []
    contours, _ = cv2.findContours(changed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        if cv2.contourArea(c) >= min_area:
            boxes.append(tuple(int(v) for v in cv2.boundingRect(c)))  # type: ignore[arg-type]
    boxes.sort(key=lambda b: b[2] * b[3], reverse=True)

    changed_bool = changed.astype(bool)
    changed_bp = int(round(10_000 * changed_bool.sum() / (h * w)))

    note = alignment.reason
    if not alignment.ok:
        note += " — geometry unreliable, so change figures are indicative only"

    return DiffResult(
        ssim_score=float(score),
        ssim_map=ssim_map,
        changed_mask=changed_bool,
        boxes=boxes,
        changed_fraction_bp=changed_bp,
        alignment_ok=alignment.ok,
        alignment_method=alignment.method,
        note=note,
    )


def changed_in_region(diff: DiffResult, region_mask: np.ndarray, label: str) -> RegionChange:
    """How much of a labelled region changed — the input to R1.

    R1's threshold is a fraction of the REGION, not of the frame: 2% of a small
    warning box is a meaningful edit even though it is a rounding error as a
    fraction of the whole creative.
    """
    if region_mask.dtype != bool:
        region_mask = region_mask.astype(bool)
    if region_mask.shape != diff.changed_mask.shape:
        raise ValueError(
            f"region mask {region_mask.shape} does not match frame {diff.changed_mask.shape}; "
            "masks must already be in master coordinates"
        )

    region_pixels = int(region_mask.sum())
    changed_pixels = int(np.logical_and(region_mask, diff.changed_mask).sum())
    fraction_bp = int(round(10_000 * changed_pixels / region_pixels)) if region_pixels else 0

    return RegionChange(
        label=label,
        region_pixels=region_pixels,
        changed_pixels=changed_pixels,
        fraction_bp=fraction_bp,
    )
