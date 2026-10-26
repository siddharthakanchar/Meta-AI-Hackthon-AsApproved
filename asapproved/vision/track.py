"""Deterministic region tracking — the keyless stand-in for SAM 3.1 (C4).

Why this exists rather than reading the labels. The variant label file records
exactly which frames the warning is visible in. Using it to answer "is the
warning visible?" would make every recall number a tautology: the detector would
be reading the answer key. So visibility is recovered from pixels here, by a
method that knows nothing about how the variant was made.

Method: take the region from the approved master, map it into variant
coordinates through the alignment homography (so a zoomed or cropped variant is
compared at the right scale), then match it frame by frame with normalised
cross-correlation. TM_CCOEFF_NORMED subtracts the mean before correlating, which
is what keeps a brightness-lifted variant from reading as "warning missing".

This is a real detector with real failure modes, not a mock. Phase 4 swaps SAM
in behind the same interface and the two get compared on region IoU (§10), which
is only a meaningful comparison because this one is honest.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from asapproved.vision.align import Alignment, to_gray

__all__ = ["RegionTrack", "track_region", "MATCH_THRESHOLD", "region_template"]

# Normalised cross-correlation score above which the region counts as present.
# 0.55 is deliberately permissive: the cost of a false "missing" is an unjust
# finding against an advertiser, while a false "present" is caught downstream by
# the contrast and geometry rules. Tuned on VariantBench-UK benign variants and
# reported with the benchmark rather than hidden here.
MATCH_THRESHOLD = 0.55

# Below this fraction of the template still inside the frame, treat the region as
# gone rather than matched-but-clipped.
MIN_INSIDE_FRACTION = 0.35


@dataclass(frozen=True)
class RegionTrack:
    label: str
    visible: list[bool]
    boxes: list[tuple[int, int, int, int] | None]
    scores: list[float]
    method: str = "template_ncc"

    @property
    def any_visible(self) -> bool:
        return any(self.visible)

    def first_box(self) -> tuple[int, int, int, int] | None:
        for box in self.boxes:
            if box is not None:
                return box
        return None


def region_template(
    master_bgr: np.ndarray,
    box: tuple[int, int, int, int],
    alignment: Alignment | None = None,
) -> np.ndarray | None:
    """Crop the region from the master and scale it into variant coordinates.

    Returns None when the region is too small to match reliably — better to
    report "not measured" than to match noise.
    """
    x, y, w, h = box
    H, W = master_bgr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 - x0 < 12 or y1 - y0 < 8:
        return None

    patch = master_bgr[y0:y1, x0:x1]

    if alignment is not None and alignment.ok:
        # Map the master box's corners into variant space to recover the scale
        # the variant actually renders this region at.
        corners = np.array(
            [[x0, y0], [x1 - 1, y0], [x1 - 1, y1 - 1], [x0, y1 - 1]], dtype=np.float64
        )
        mapped = alignment.map_points_inverse(corners)
        tw = int(round(max(np.linalg.norm(mapped[1] - mapped[0]), 1)))
        th = int(round(max(np.linalg.norm(mapped[3] - mapped[0]), 1)))
        if 8 <= tw <= 4000 and 6 <= th <= 4000 and (tw, th) != (patch.shape[1], patch.shape[0]):
            patch = cv2.resize(patch, (tw, th), interpolation=cv2.INTER_AREA)

    if patch.shape[0] < 6 or patch.shape[1] < 8:
        return None
    return patch


def track_region(
    template_bgr: np.ndarray,
    frames: list[np.ndarray],
    label: str,
    *,
    threshold: float = MATCH_THRESHOLD,
) -> RegionTrack:
    """Find the template in each frame. Absent frames report visible=False."""
    tmpl = to_gray(template_bgr)
    th, tw = tmpl.shape[:2]

    visible: list[bool] = []
    boxes: list[tuple[int, int, int, int] | None] = []
    scores: list[float] = []

    for frame in frames:
        gray = to_gray(frame)
        fh, fw = gray.shape[:2]

        if fh < th or fw < tw:
            # The frame is smaller than the region we are looking for — a hard
            # crop. Match what still fits, so a partially cropped warning is
            # detected as present-but-clipped rather than vanishing silently.
            ch, cw = min(th, fh), min(tw, fw)
            inside = (ch * cw) / float(th * tw)
            if inside < MIN_INSIDE_FRACTION:
                visible.append(False)
                boxes.append(None)
                scores.append(0.0)
                continue
            sub = tmpl[:ch, :cw]
        else:
            sub = tmpl

        result = cv2.matchTemplate(gray, sub, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        score = float(max_val) if np.isfinite(max_val) else 0.0

        if score >= threshold:
            visible.append(True)
            boxes.append((int(max_loc[0]), int(max_loc[1]), int(sub.shape[1]), int(sub.shape[0])))
        else:
            visible.append(False)
            boxes.append(None)
        scores.append(score)

    return RegionTrack(label=label, visible=visible, boxes=boxes, scores=scores)
