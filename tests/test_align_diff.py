"""C3 — alignment and diff, over the five synthetic geometry cases."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from asapproved.vision.align import align_to_master, warp_to_master
from asapproved.vision.diff import changed_in_region, diff_pair
from tests.conftest import warning_box

# --------------------------------------------------------------------------
# the five geometry cases from C3's acceptance criteria
# --------------------------------------------------------------------------


def _crop(img, left=60, top=90):
    return img[top:, left:]


def _expand(img, pad=70):
    return cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)


def _zoom(img, factor=1.25):
    h, w = img.shape[:2]
    big = cv2.resize(img, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_LINEAR)
    y = (big.shape[0] - h) // 2
    x = (big.shape[1] - w) // 2
    return big[y : y + h, x : x + w]


def _scale_down(img, factor=0.7):
    h, w = img.shape[:2]
    return cv2.resize(img, (int(w * factor), int(h * factor)), interpolation=cv2.INTER_AREA)


@pytest.mark.parametrize(
    "name,transform",
    [
        ("identity", lambda im: im.copy()),
        ("crop", _crop),
        ("expand", _expand),
        ("zoom", _zoom),
        ("scale_down", _scale_down),
    ],
)
def test_alignment_recovers_geometry(master, name, transform):
    variant = transform(master)
    alignment = align_to_master(master, variant)

    assert alignment.ok, f"{name}: {alignment.reason}"
    assert alignment.method == "homography"
    assert alignment.confident

    # The real test is not the matrix but the consequence: warping the variant
    # back into master coordinates should reproduce the master.
    warped = warp_to_master(variant, alignment)
    assert warped.shape[:2] == master.shape[:2]

    mg = cv2.cvtColor(master, cv2.COLOR_BGR2GRAY).astype(np.int16)
    wg = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.int16)
    valid = wg > 0  # ignore the black border a crop leaves behind
    mean_abs = float(np.abs(mg[valid] - wg[valid]).mean())
    assert mean_abs < 18, f"{name}: mean abs error {mean_abs:.1f} after warp-back"


def test_alignment_maps_a_known_point(master):
    """A point in the variant must land on the same content in the master."""
    variant = _crop(master, left=60, top=90)
    alignment = align_to_master(master, variant)
    assert alignment.ok

    # The crop moved content up-left by (60, 90), so variant (x,y) == master (x+60, y+90).
    mapped = alignment.map_points(np.array([[200.0, 400.0]]))[0]
    assert mapped[0] == pytest.approx(260, abs=6)
    assert mapped[1] == pytest.approx(490, abs=6)


def test_featureless_input_falls_back_and_says_so(master):
    """A flat frame cannot be aligned. It must degrade loudly, not silently."""
    flat = np.full_like(master, 120)
    alignment = align_to_master(flat, flat)

    assert not alignment.ok
    assert alignment.method == "resize"
    assert not alignment.confident
    assert "scale-only" in alignment.reason


def test_unreliable_alignment_marks_the_diff_untrustworthy(master):
    flat = np.full_like(master, 120)
    result = diff_pair(flat, np.full_like(master, 121))
    assert not result.trustworthy
    assert "geometry unreliable" in result.note


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------


def test_identical_pair_shows_no_change(master):
    result = diff_pair(master, master.copy())
    assert result.ssim_score > 0.99
    assert result.changed_fraction_bp < 50  # <0.5% of frame
    assert result.trustworthy


def test_edit_inside_the_warning_is_localised_there(master, warning_mask, apr_mask):
    """The R1 signal: change intersected with the warning region, not frame-wide."""
    variant = master.copy()
    x, y, w, h = warning_box()
    # Overwrite the warning text with background colour — the "quietly removed" case.
    cv2.rectangle(variant, (x + 10, y + 20), (x + w - 10, y + h - 15), (255, 255, 255), -1)

    result = diff_pair(master, variant)
    assert result.trustworthy

    in_warning = changed_in_region(result, warning_mask, "risk warning box")
    in_apr = changed_in_region(result, apr_mask, "APR text")

    assert in_warning.fraction_bp > 200, "a wiped warning must read as changed"
    assert in_apr.fraction_bp < 200, "the untouched APR must not be implicated"
    assert in_warning.exceeds_bp(200)  # R1 default tau = 2% = 200bp
    assert not in_apr.exceeds_bp(200)


def test_brightness_shift_registers_less_than_a_structural_edit(master, warning_mask):
    """SSIM is chosen over absolute diff precisely for this.

    Not asserting "zero" — a brightness shift does move SSIM. Asserting that a
    benign global edit reads as substantially smaller than content removal, which
    is what keeps the false-block rate on benign variants low.
    """
    brighter = cv2.convertScaleAbs(master, alpha=1.0, beta=22)

    wiped = master.copy()
    x, y, w, h = warning_box()
    cv2.rectangle(wiped, (x + 10, y + 20), (x + w - 10, y + h - 15), (255, 255, 255), -1)

    benign = changed_in_region(diff_pair(master, brighter), warning_mask, "w").fraction_bp
    structural = changed_in_region(diff_pair(master, wiped), warning_mask, "w").fraction_bp
    assert structural > benign * 2, f"benign={benign}bp structural={structural}bp"


def test_region_mask_shape_mismatch_is_rejected(master):
    result = diff_pair(master, master.copy())
    wrong = np.zeros((10, 10), dtype=bool)
    with pytest.raises(ValueError, match="master coordinates"):
        changed_in_region(result, wrong, "risk warning box")


def test_changed_boxes_are_sorted_largest_first(master):
    variant = master.copy()
    cv2.rectangle(variant, (50, 500), (300, 700), (0, 0, 255), -1)
    cv2.rectangle(variant, (400, 820), (430, 850), (0, 255, 0), -1)

    result = diff_pair(master, variant)
    assert len(result.boxes) >= 2
    areas = [w * h for _, _, w, h in result.boxes]
    assert areas == sorted(areas, reverse=True)


def test_ratios_are_integers_for_the_evidence_chain(master, warning_mask):
    result = diff_pair(master, master.copy())
    change = changed_in_region(result, warning_mask, "risk warning box")
    assert isinstance(change.fraction_bp, int)
    assert isinstance(result.changed_fraction_bp, int)
