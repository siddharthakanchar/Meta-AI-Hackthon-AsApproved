"""C5 — the measurement engine. Every number a finding can quote starts here."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from asapproved.canonical import assert_no_floats
from asapproved.measure import (
    bbox_of,
    contrast_ratio,
    detect_border,
    is_clipped,
    measure_contrast,
    measure_region,
    measure_track,
    relative_luminance,
)
from tests.conftest import FRAME_H, FRAME_W, region_mask, warning_box

# --------------------------------------------------------------------------
# WCAG contrast
# --------------------------------------------------------------------------


def test_relative_luminance_endpoints():
    assert float(relative_luminance(np.array([0, 0, 0]))) == pytest.approx(0.0, abs=1e-9)
    assert float(relative_luminance(np.array([255, 255, 255]))) == pytest.approx(1.0, abs=1e-9)


def test_contrast_ratio_known_values():
    black = float(relative_luminance(np.array([0, 0, 0])))
    white = float(relative_luminance(np.array([255, 255, 255])))
    assert contrast_ratio(white, black) == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio(white, white) == pytest.approx(1.0, abs=0.01)
    # Order must not matter — callers should not have to know which is lighter.
    assert contrast_ratio(black, white) == pytest.approx(contrast_ratio(white, black))


def test_measure_contrast_black_on_white_is_near_maximum():
    img = np.full((120, 400, 3), 255, dtype=np.uint8)
    cv2.putText(img, "24.9% APR", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)
    mask = np.ones(img.shape[:2], dtype=bool)

    ratio = measure_contrast(img, mask)
    assert ratio is not None
    assert ratio > 1500, f"black on white should approach 21:1, got {ratio / 100:.1f}:1"


def test_measure_contrast_grey_on_grey_fails_wcag():
    """The R6 case: a background swap that leaves the text barely legible."""
    img = np.full((120, 400, 3), 150, dtype=np.uint8)
    cv2.putText(img, "24.9% APR", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (120, 120, 120), 4)
    mask = np.ones(img.shape[:2], dtype=bool)

    ratio = measure_contrast(img, mask)
    assert ratio is not None
    assert ratio < 450, f"expected below the 4.5:1 threshold, got {ratio / 100:.2f}:1"


def test_measure_contrast_returns_none_on_flat_region():
    """No bimodal split means no honest answer — report None, never a number."""
    img = np.full((120, 400, 3), 200, dtype=np.uint8)
    mask = np.ones(img.shape[:2], dtype=bool)
    assert measure_contrast(img, mask) is None


def test_measure_contrast_returns_none_on_tiny_region():
    img = np.full((120, 400, 3), 200, dtype=np.uint8)
    mask = np.zeros(img.shape[:2], dtype=bool)
    mask[0:3, 0:3] = True
    assert measure_contrast(img, mask) is None


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------


def test_bbox_of_empty_mask_is_none():
    assert bbox_of(np.zeros((50, 50), dtype=bool)) is None


def test_bbox_is_inclusive_of_both_edges():
    mask = np.zeros((50, 50), dtype=bool)
    mask[10:20, 5:15] = True
    assert bbox_of(mask) == (5, 10, 10, 10)


def test_is_clipped_detects_edge_contact():
    middle = region_mask(FRAME_W, FRAME_H, (100, 400, 200, 80))
    assert not is_clipped(middle)

    at_bottom = np.zeros((FRAME_H, FRAME_W), dtype=bool)
    at_bottom[FRAME_H - 40 :, 100:300] = True
    assert is_clipped(at_bottom)

    at_left = np.zeros((FRAME_H, FRAME_W), dtype=bool)
    at_left[400:480, :60] = True
    assert is_clipped(at_left)


def test_detect_border_finds_a_drawn_box():
    img = np.full((200, 400, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (380, 180), (0, 0, 0), 3)
    assert detect_border(img, (20, 20, 360, 160)) is True


def test_detect_border_false_when_there_is_none():
    img = np.full((200, 400, 3), 255, dtype=np.uint8)
    cv2.putText(img, "warning text", (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    assert detect_border(img, (20, 20, 360, 160)) is False


def test_detect_border_inconclusive_on_tiny_box():
    """Too small to judge returns None — not a finding against the advertiser."""
    img = np.full((200, 400, 3), 255, dtype=np.uint8)
    assert detect_border(img, (10, 10, 8, 6)) is None


# --------------------------------------------------------------------------
# per-region measurement
# --------------------------------------------------------------------------


def test_measure_region_on_the_warning_box(master, warning_mask):
    m = measure_region(master, warning_mask, "risk warning box", placement="reels")

    assert m.present
    assert m.label == "risk warning box"
    assert m.bbox == warning_box()
    assert m.height_bp == pytest.approx(int(round(10_000 * 110 / FRAME_H)), abs=2)
    assert m.hd_lines is not None and m.hd_lines > 0
    assert m.contrast_x100 is not None and m.contrast_x100 > 1000
    assert m.border_present is True
    assert m.occlusion is not None and m.occlusion.any_occluded


def test_measure_region_absent_region(master):
    empty = np.zeros((FRAME_H, FRAME_W), dtype=bool)
    m = measure_region(master, empty, "risk warning box")

    assert not m.present
    assert m.bbox is None
    assert m.pixels == 0
    assert m.contrast_x100 is None
    assert m.border_present is None


def test_measure_region_record_is_chain_safe(master, warning_mask):
    record = measure_region(master, warning_mask, "risk warning box", placement="reels").to_record()
    assert_no_floats(record)  # raises if any float slipped in
    import json

    json.dumps(record)  # and no numpy scalars


def test_inconclusive_fields_are_named(master):
    flat = np.full_like(master, 200)
    mask = region_mask(FRAME_W, FRAME_H, (100, 400, 300, 90))
    m = measure_region(flat, mask, "risk warning box")
    assert "contrast" in m.inconclusive_fields


# --------------------------------------------------------------------------
# visibility across a clip
# --------------------------------------------------------------------------


def test_measure_track_the_hero_number():
    """The demo line: APR on screen 1.2s of 15s at 25fps."""
    fps = 25.0
    total = 375  # 15s
    visible = [True] * 30 + [False] * (total - 30)  # 1.2s

    t = measure_track(visible, fps, label="APR text")
    assert t.ms_visible == 1200
    assert t.ms_total == 15000
    assert t.visible_ratio_bp == 800  # 8%
    assert t.first_visible_frame == 0
    assert t.last_visible_frame == 29
    assert t.human() == "on screen 1.2 s of 15 s"


def test_measure_track_full_visibility_passes_r4():
    t = measure_track([True] * 375, 25.0)
    assert t.visible_ratio_bp == 10_000
    assert t.longest_gap_frames == 0


def test_longest_gap_separates_flicker_from_a_real_dropout():
    """R4's ratio alone cannot tell these apart; the gap can.

    Both clips are visible for 98% of frames. One flickers imperceptibly, the
    other loses the warning for a third of a second.
    """
    flicker = [True] * 375
    for i in range(0, 375, 50):
        flicker[i] = False  # 8 isolated frames

    dropout = [True] * 375
    dropout[100:108] = [False] * 8  # same count, one run

    a = measure_track(flicker, 25.0)
    b = measure_track(dropout, 25.0)

    assert a.visible_ratio_bp == b.visible_ratio_bp
    assert a.longest_gap_frames == 1
    assert b.longest_gap_frames == 8


def test_measure_track_never_visible():
    t = measure_track([False] * 100, 25.0)
    assert t.ms_visible == 0
    assert t.visible_ratio_bp == 0
    assert t.first_visible_frame is None
    assert t.last_visible_frame is None
    assert t.longest_gap_frames == 100


def test_measure_track_record_is_chain_safe():
    record = measure_track([True] * 10 + [False] * 5, 25.0).to_record()
    assert_no_floats(record)


def test_measure_track_rejects_bad_input():
    with pytest.raises(ValueError, match="no frames"):
        measure_track([], 25.0)
    with pytest.raises(ValueError, match="bad fps"):
        measure_track([True], 0)
