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


def expected_box(
    master_box: tuple[int, int, int, int],
    alignment: Alignment | None,
    variant_shape: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    """Where the master's region should land in the variant, per the alignment.

    This is the positional prior that stops an appearance change from reading as
    a disappearance. A warning set grey-on-grey, shrunk, or reworded no longer
    matches its own template — but it has not moved, and measuring at the place
    it should be is what lets R6, R7 and R11 fire instead of everything
    collapsing into "the warning is gone".
    """
    if alignment is None or not alignment.ok:
        return None
    x, y, w, h = master_box
    corners = np.array(
        [[x, y], [x + w - 1, y], [x + w - 1, y + h - 1], [x, y + h - 1]], dtype=np.float64
    )
    mapped = alignment.map_points_inverse(corners)
    x0, y0 = mapped[:, 0].min(), mapped[:, 1].min()
    x1, y1 = mapped[:, 0].max(), mapped[:, 1].max()
    if not all(np.isfinite(v) for v in (x0, y0, x1, y1)):
        return None
    return int(round(x0)), int(round(y0)), int(round(x1 - x0 + 1)), int(round(y1 - y0 + 1))


def inside_fraction(box: tuple[int, int, int, int], shape: tuple[int, int]) -> float:
    """How much of the box lies within the frame, 0..1."""
    h, w = shape[:2]
    x, y, bw, bh = box
    ox = max(0, min(w, x + bw) - max(0, x))
    oy = max(0, min(h, y + bh) - max(0, y))
    area = bw * bh
    return (ox * oy) / area if area else 0.0


def track_region(
    template_bgr: np.ndarray,
    frames: list[np.ndarray],
    label: str,
    *,
    threshold: float = MATCH_THRESHOLD,
    near: tuple[int, int, int, int] | None = None,
    search_margin: float = 0.35,
) -> RegionTrack:
    """Find the template in each frame. Absent frames report visible=False.

    `near` restricts the search to a neighbourhood of the expected position.
    Without it the matcher searches globally and will happily match the APR's
    template onto the trigger — same typeface, same weight, same colour, same
    background — so an APR that has slid off screen still reports as present and
    R8's prominence comparison finds nothing wrong.
    """
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

        # Restrict the haystack to a neighbourhood of where the region is
        # expected, when we know. Global search confuses visually identical
        # elements — see the docstring.
        ox = oy = 0
        haystack = gray
        if near is not None:
            nx, ny, nw, nh = near
            mx, my = int(sub.shape[1] * search_margin), int(sub.shape[0] * search_margin)
            ox = max(0, nx - mx)
            oy = max(0, ny - my)
            x1 = min(fw, nx + nw + mx)
            y1 = min(fh, ny + nh + my)
            if x1 - ox >= sub.shape[1] and y1 - oy >= sub.shape[0]:
                haystack = gray[oy:y1, ox:x1]
            else:
                ox = oy = 0

        result = cv2.matchTemplate(haystack, sub, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        score = float(max_val) if np.isfinite(max_val) else 0.0

        if score >= threshold:
            visible.append(True)
            boxes.append(
                (int(max_loc[0] + ox), int(max_loc[1] + oy), int(sub.shape[1]), int(sub.shape[0]))
            )
        else:
            visible.append(False)
            boxes.append(None)
        scores.append(score)

    return RegionTrack(label=label, visible=visible, boxes=boxes, scores=scores)
