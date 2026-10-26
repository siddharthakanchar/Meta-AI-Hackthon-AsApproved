"""C3 part 1 — align a variant to its approved master.

Meta's enhancements crop, expand, zoom, pan and rescale. Comparing raw pixels
without undoing that geometry produces a diff that is 100% "changed" and says
nothing. So: ORB keypoints, ratio-tested matches, RANSAC homography, variant
mapped back into master coordinates.

The honest part is the failure path. A homography fitted to a handful of noisy
matches can look plausible and be badly wrong, and a wrong alignment produces
confident nonsense downstream — a warning declared "missing" because it was
mapped off-frame. So alignment reports its own confidence, refuses to return a
transform it does not trust, and falls back to a plain resize that is clearly
labelled as such. `Alignment.ok` gates whether the geometry-dependent rules
(R1, R3) are allowed to fire at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

__all__ = ["Alignment", "align_to_master", "warp_to_master", "to_gray"]

# A homography needs 4 correspondences; 4 is also trivially satisfiable by noise.
# 12 inliers is a pragmatic floor for the synthetic ad creative we work with —
# flat colour, large text, few corners — chosen to reject junk rather than to
# squeeze out the last few percent of recall. Tuned in Phase 3 against real
# variants; the value lives here rather than being scattered through callers.
MIN_INLIERS = 12
RATIO_TEST = 0.75
RANSAC_REPROJ_PX = 3.0


def to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


@dataclass(frozen=True)
class Alignment:
    """How to map variant pixels into master coordinates.

    `matrix` maps variant -> master. `inverse` maps master -> variant, which is
    what you need to ask "where did the master's warning box end up?".
    """

    matrix: np.ndarray
    inverse: np.ndarray
    method: str  # "homography" | "resize"
    matches: int
    inliers: int
    ok: bool
    reason: str
    master_shape: tuple[int, int]  # (h, w)

    @property
    def confident(self) -> bool:
        return self.ok and self.method == "homography"

    def map_points(self, points: np.ndarray) -> np.ndarray:
        """Map (N,2) variant points into master coordinates."""
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, self.matrix).reshape(-1, 2)

    def map_points_inverse(self, points: np.ndarray) -> np.ndarray:
        """Map (N,2) master points into variant coordinates."""
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, self.inverse).reshape(-1, 2)


def _resize_alignment(
    master_shape: tuple[int, int], variant_shape: tuple[int, int], reason: str
) -> Alignment:
    """Scale-only fallback. Correct for a pure rescale, wrong for a crop — labelled."""
    mh, mw = master_shape
    vh, vw = variant_shape
    sx, sy = mw / vw, mh / vh
    matrix = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], dtype=np.float64)
    return Alignment(
        matrix=matrix,
        inverse=np.linalg.inv(matrix),
        method="resize",
        matches=0,
        inliers=0,
        ok=False,
        reason=reason,
        master_shape=master_shape,
    )


def align_to_master(master: np.ndarray, variant: np.ndarray, *, nfeatures: int = 5000) -> Alignment:
    """Estimate the variant -> master transform.

    Returns an Alignment whose `ok` is False when the estimate cannot be trusted;
    callers must check it before relying on mapped geometry.
    """
    mg, vg = to_gray(master), to_gray(variant)
    master_shape = (mg.shape[0], mg.shape[1])
    variant_shape = (vg.shape[0], vg.shape[1])

    orb = cv2.ORB_create(nfeatures=nfeatures)
    kp_m, des_m = orb.detectAndCompute(mg, None)
    kp_v, des_v = orb.detectAndCompute(vg, None)

    if des_m is None or des_v is None or len(kp_m) < 4 or len(kp_v) < 4:
        return _resize_alignment(
            master_shape,
            variant_shape,
            "too few keypoints to align (flat or featureless creative); "
            "fell back to scale-only",
        )

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    raw = matcher.knnMatch(des_v, des_m, k=2)
    good = [m for pair in raw if len(pair) == 2 for m, n in [pair] if m.distance < RATIO_TEST * n.distance]

    if len(good) < MIN_INLIERS:
        return _resize_alignment(
            master_shape,
            variant_shape,
            f"only {len(good)} ratio-tested matches (need {MIN_INLIERS}); fell back to scale-only",
        )

    src = np.float32([kp_v[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_m[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_REPROJ_PX)

    if matrix is None:
        return _resize_alignment(
            master_shape, variant_shape, "homography did not converge; fell back to scale-only"
        )

    inliers = int(mask.sum()) if mask is not None else 0
    if inliers < MIN_INLIERS:
        return _resize_alignment(
            master_shape,
            variant_shape,
            f"homography kept only {inliers} inliers (need {MIN_INLIERS}); "
            "fell back to scale-only",
        )

    # A homography can be numerically valid and geometrically absurd (collapsed or
    # mirrored). Reject degenerate transforms rather than propagate them.
    det = float(np.linalg.det(matrix[:2, :2]))
    if not np.isfinite(det) or abs(det) < 1e-6:
        return _resize_alignment(
            master_shape, variant_shape, "degenerate homography (collapsed); fell back to scale-only"
        )

    return Alignment(
        matrix=matrix.astype(np.float64),
        inverse=np.linalg.inv(matrix).astype(np.float64),
        method="homography",
        matches=len(good),
        inliers=inliers,
        ok=True,
        reason=f"homography from {inliers}/{len(good)} inlier matches",
        master_shape=master_shape,
    )


def warp_to_master(variant: np.ndarray, alignment: Alignment) -> np.ndarray:
    """Render the variant in master coordinates, ready for pixel comparison."""
    h, w = alignment.master_shape
    return cv2.warpPerspective(
        variant, alignment.matrix, (w, h), flags=cv2.INTER_LINEAR, borderValue=0
    )
