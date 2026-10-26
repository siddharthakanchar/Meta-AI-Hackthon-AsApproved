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

# Long-line coverage along each side of the warning box, calibrated by
# measurement rather than by eye. On VariantBench-UK a drawn border scores
# [0.86, 0.86, 0.59, 0.57] — the vertical sides read lower because the line is
# shorter relative to the search band — and a removed one scores [0, 0, 0, 0].
# The thresholds sit in that gap. Between them, `detect_border` returns None.
BORDER_PRESENT_ABOVE = 0.45
BORDER_ABSENT_BELOW = 0.20


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

    Looks for a LONG STRAIGHT LINE along each side, not merely edge pixels.
    That distinction is the whole difficulty: text produces plenty of edge
    response, so "are there edges near the perimeter?" reported a border on
    variants where it had been removed, while "are there edges exactly at the
    box edge?" reported none on variants that had one — because the box we are
    given is often the text's bounding box, and the border sits outside it with
    padding between.

    Three outcomes. Where the warning is set at very low contrast the border may
    be present and genuinely undetectable, and saying so is better than
    guessing in either direction (V14).
    """
    x, y, w, h = bbox
    if w < 20 or h < 12:
        return None
    H, W = frame_bgr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 - x0 < 20 or y1 - y0 < 12:
        return None

    # Search a margin outside the box too: the border encloses the text with
    # padding, so it is usually not on the text's own bounding edge.
    reach = max(6, int(min(x1 - x0, y1 - y0) * 0.35))
    rx0, ry0 = max(0, x0 - reach), max(0, y0 - reach)
    rx1, ry1 = min(W, x1 + reach), min(H, y1 + reach)
    region = frame_bgr[ry0:ry1, rx0:rx1]
    if region.size == 0 or region.shape[0] < 12 or region.shape[1] < 20:
        return None

    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if region.ndim == 3 else region
    edges = cv2.Canny(gray, 40, 120)
    rh, rw = edges.shape[:2]

    # Keep only runs long enough to be a drawn rule rather than a glyph stroke.
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, rw // 3), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(8, rh // 3)))
    h_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, v_kernel)

    def best_row_coverage(mask: np.ndarray, rows: range) -> float:
        best = 0.0
        for r in rows:
            if 0 <= r < mask.shape[0]:
                best = max(best, float((mask[r] > 0).mean()))
        return best

    def best_col_coverage(mask: np.ndarray, cols: range) -> float:
        best = 0.0
        for c in cols:
            if 0 <= c < mask.shape[1]:
                best = max(best, float((mask[:, c] > 0).mean()))
        return best

    inset_y, inset_x = y0 - ry0, x0 - rx0
    span_y, span_x = y1 - y0, x1 - x0

    coverage = [
        best_row_coverage(h_lines, range(0, inset_y + 3)),
        best_row_coverage(h_lines, range(inset_y + span_y - 3, rh)),
        best_col_coverage(v_lines, range(0, inset_x + 3)),
        best_col_coverage(v_lines, range(inset_x + span_x - 3, rw)),
    ]

    # Count sides, do not demand all four. Measured across the twelve masters,
    # a drawn border scores at worst [0.86, 0.63, 0.59, 0.00]: on 9:16 creative
    # the right-hand rule consistently drops out, because the box runs close to
    # the frame edge and the search window is clipped there. A removed border
    # scores [0, 0, 0, 0]. Three detected sides is therefore a box; one or none
    # is not; two is genuinely ambiguous and says so.
    detected = sum(1 for c in coverage if c >= BORDER_PRESENT_ABOVE)
    if detected >= 3:
        return True
    if sum(1 for c in coverage if c >= BORDER_ABSENT_BELOW) <= 1:
        return False
    return None


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
