"""C5 — the measurement engine.

Every number that ends up in a finding, a compliance note or the evidence chain
is produced here. Deterministic, no model calls, unit-tested: if a regulator asks
"where does 1.2 seconds come from", the answer is a function and a frame range,
not a language model.

Two conventions, both load-bearing:

1. **No floats leave this module in signed form.** Values are integers in fixed
   units — milliseconds, basis points, hundredths of a contrast ratio, pixels —
   because floats do not round-trip reliably and the evidence chain must verify
   on a machine that is not the one that wrote it. See `canonical.assert_no_floats`.

2. **Unmeasurable is reported, never guessed.** Anything this module cannot
   establish confidently returns `None` and surfaces as `inconclusive` rather than
   as a pass or a fail. A compliance tool that quietly guesses is worse than one
   that admits the gap (V14).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from asapproved.vision.overlays import Occlusion, occlusion

__all__ = [
    "relative_luminance",
    "contrast_ratio",
    "measure_contrast",
    "detect_border",
    "is_clipped",
    "RegionMeasurement",
    "measure_region",
    "TrackMeasurement",
    "measure_track",
    "bbox_of",
]

HD_REFERENCE_LINES = 1080  # "HD-line equivalents" are relative to a 1080-line frame


# --------------------------------------------------------------------------
# contrast (WCAG 2.x)
# --------------------------------------------------------------------------


def relative_luminance(rgb: np.ndarray) -> np.ndarray:
    """WCAG relative luminance for sRGB values in 0..255. Accepts (...,3) RGB."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def contrast_ratio(lum_a: float, lum_b: float) -> float:
    """WCAG contrast ratio, 1.0 .. 21.0. Order-independent."""
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def measure_contrast(frame_bgr: np.ndarray, region_mask: np.ndarray) -> int | None:
    """Contrast between the text and its immediate background, x100 as an int.

    Method, stated because it is a proxy and should be read as one: inside the
    region, split pixels into ink and ground with Otsu on luminance, then take the
    median luminance of each side. Medians rather than means so antialiased edge
    pixels — which sit between the two populations — do not drag the figure toward
    the middle and flatter a genuinely low-contrast warning.

    Returns None when the region is too small or has no usable bimodal split
    (e.g. a solid block of one colour), rather than inventing a ratio.
    """
    if region_mask.dtype != bool:
        region_mask = region_mask.astype(bool)
    if region_mask.sum() < 50:
        return None

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB) if frame_bgr.ndim == 3 else None
    if rgb is None:
        return None

    lum = relative_luminance(rgb)
    values = lum[region_mask]

    # Otsu needs 8-bit; operate on perceptual luminance, not raw channel values.
    as_u8 = np.clip(values * 255.0, 0, 255).astype(np.uint8)
    if as_u8.min() == as_u8.max():
        return None
    threshold, _ = cv2.threshold(as_u8.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    dark = values[as_u8 <= threshold]
    light = values[as_u8 > threshold]
    if dark.size < 10 or light.size < 10:
        return None

    ratio = contrast_ratio(float(np.median(light)), float(np.median(dark)))
    return int(round(ratio * 100))


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------


def bbox_of(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of a boolean mask, or None if empty."""
    if mask.dtype != bool:
        mask = mask.astype(bool)
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return None
    y0, y1 = int(rows[0]), int(rows[-1])
    x0, x1 = int(cols[0]), int(cols[-1])
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def is_clipped(mask: np.ndarray, *, margin: int = 1) -> bool:
    """True when the region touches the frame edge — i.e. may continue off-frame.

    This is deliberately a "may be truncated" signal, not proof of truncation: a
    warning legitimately flush to the edge trips it too. R3 pairs it with the
    master comparison, which is what turns a suspicion into a finding.
    """
    box = bbox_of(mask)
    if box is None:
        return False
    x, y, w, h = box
    H, W = mask.shape[:2]
    return x <= margin - 1 or y <= margin - 1 or (x + w) >= W - margin + 1 or (y + h) >= H - margin + 1


def detect_border(frame_bgr: np.ndarray, bbox: tuple[int, int, int, int]) -> bool | None:
    """Is the region enclosed in its own border? (COBS 4.12A.36R)

    Looks for sustained edge response along all four sides of the bounding box.
    Returns None — inconclusive — when the box is too small to judge, rather than
    reporting a confident False that would become a finding against the advertiser.
    """
    x, y, w, h = bbox
    if w < 20 or h < 12:
        return None
    H, W = frame_bgr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 - x0 < 20 or y1 - y0 < 12:
        return None

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
    edges = cv2.Canny(gray, 50, 150)

    band = max(2, min(4, (y1 - y0) // 10, (x1 - x0) // 10))
    sides = {
        "top": edges[y0 : y0 + band, x0:x1],
        "bottom": edges[max(y0, y1 - band) : y1, x0:x1],
        "left": edges[y0:y1, x0 : x0 + band],
        "right": edges[y0:y1, max(x0, x1 - band) : x1],
    }
    # A side counts as present if edge pixels cover most of its length.
    present = []
    for name, strip in sides.items():
        if strip.size == 0:
            return None
        axis = 0 if name in ("top", "bottom") else 1
        covered = (strip > 0).any(axis=axis).mean()
        present.append(covered >= 0.80)
    return all(present)


# --------------------------------------------------------------------------
# per-region measurement
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RegionMeasurement:
    """All of C5's per-region numbers. Integers only — chain-safe."""

    label: str
    present: bool
    bbox: tuple[int, int, int, int] | None
    pixels: int
    frame_width: int
    frame_height: int
    height_bp: int | None  # region height as basis points of frame height
    hd_lines: int | None  # height in 1080-line equivalents
    contrast_x100: int | None  # None = could not measure
    border_present: bool | None  # None = inconclusive
    clipped: bool
    occlusion: Occlusion | None

    @property
    def inconclusive_fields(self) -> list[str]:
        out = []
        if self.contrast_x100 is None:
            out.append("contrast")
        if self.border_present is None:
            out.append("border")
        return out

    def to_record(self) -> dict:
        """Chain-safe dict for the evidence log — no floats, no numpy types."""
        return {
            "label": self.label,
            "present": self.present,
            "bbox": list(self.bbox) if self.bbox else None,
            "pixels": self.pixels,
            "frame": [self.frame_width, self.frame_height],
            "height_bp": self.height_bp,
            "hd_lines": self.hd_lines,
            "contrast_x100": self.contrast_x100,
            "border_present": self.border_present,
            "clipped": self.clipped,
            "occluded_pixels": self.occlusion.occluded_pixels if self.occlusion else None,
            "occlusion_bp": self.occlusion.fraction_bp if self.occlusion else None,
            "inconclusive": self.inconclusive_fields,
        }


def measure_region(
    frame_bgr: np.ndarray,
    region_mask: np.ndarray,
    label: str,
    *,
    placement: str | None = None,
) -> RegionMeasurement:
    """Measure one labelled region in one frame."""
    if region_mask.dtype != bool:
        region_mask = region_mask.astype(bool)
    H, W = region_mask.shape[:2]
    box = bbox_of(region_mask)
    pixels = int(region_mask.sum())

    if box is None:
        return RegionMeasurement(
            label=label,
            present=False,
            bbox=None,
            pixels=0,
            frame_width=W,
            frame_height=H,
            height_bp=None,
            hd_lines=None,
            contrast_x100=None,
            border_present=None,
            clipped=False,
            occlusion=None,
        )

    _, _, _, h = box
    return RegionMeasurement(
        label=label,
        present=True,
        bbox=box,
        pixels=pixels,
        frame_width=W,
        frame_height=H,
        height_bp=int(round(10_000 * h / H)),
        hd_lines=int(round(HD_REFERENCE_LINES * h / H)),
        contrast_x100=measure_contrast(frame_bgr, region_mask),
        border_present=detect_border(frame_bgr, box),
        clipped=is_clipped(region_mask),
        occlusion=occlusion(region_mask, placement) if placement else None,
    )


# --------------------------------------------------------------------------
# across a video
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackMeasurement:
    """Visibility of one region across a clip — the input to R4 and R8.

    "On screen 1.2 s of 15" is this dataclass.
    """

    label: str
    total_frames: int
    visible_frames: int
    fps_x100: int
    ms_visible: int
    ms_total: int
    visible_ratio_bp: int
    first_visible_frame: int | None
    last_visible_frame: int | None
    longest_gap_frames: int

    def to_record(self) -> dict:
        return {
            "label": self.label,
            "total_frames": self.total_frames,
            "visible_frames": self.visible_frames,
            "fps_x100": self.fps_x100,
            "ms_visible": self.ms_visible,
            "ms_total": self.ms_total,
            "visible_ratio_bp": self.visible_ratio_bp,
            "first_visible_frame": self.first_visible_frame,
            "last_visible_frame": self.last_visible_frame,
            "longest_gap_frames": self.longest_gap_frames,
        }

    def human(self) -> str:
        """The line the UI shows big and plain: "on screen 1.2 s of 15 s"."""
        return f"on screen {self.ms_visible / 1000:.1f} s of {self.ms_total / 1000:.0f} s"


def measure_track(
    visible_by_frame: list[bool] | np.ndarray,
    fps: float,
    label: str = "warning",
) -> TrackMeasurement:
    """Turn per-frame visibility into the numbers R4 and R8 consume.

    `fps` is a float at the boundary because that is what video files report;
    it is stored as `fps_x100` so nothing downstream carries a float.
    """
    vis = np.asarray(visible_by_frame, dtype=bool)
    total = int(vis.size)
    if total == 0:
        raise ValueError("no frames to measure")
    if fps <= 0:
        raise ValueError(f"bad fps: {fps}")

    visible = int(vis.sum())
    ms_per_frame = 1000.0 / fps
    idx = np.flatnonzero(vis)

    # Longest run of consecutive invisible frames — a warning that flickers for
    # 98% of frames is not the same as one that vanishes for a third of a second,
    # and R4's ratio alone cannot tell them apart.
    longest_gap = 0
    run = 0
    for v in vis:
        run = 0 if v else run + 1
        longest_gap = max(longest_gap, run)

    return TrackMeasurement(
        label=label,
        total_frames=total,
        visible_frames=visible,
        fps_x100=int(round(fps * 100)),
        ms_visible=int(round(visible * ms_per_frame)),
        ms_total=int(round(total * ms_per_frame)),
        visible_ratio_bp=int(round(10_000 * visible / total)),
        first_visible_frame=int(idx[0]) if idx.size else None,
        last_visible_frame=int(idx[-1]) if idx.size else None,
        longest_gap_frames=int(longest_gap),
    )
