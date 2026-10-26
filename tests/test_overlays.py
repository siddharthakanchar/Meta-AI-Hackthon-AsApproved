"""C9 / R12 — placement overlay zones and occlusion."""

from __future__ import annotations

import numpy as np
import pytest

from asapproved.vision.overlays import (
    PLACEMENTS,
    get_spec,
    load_placements,
    occlusion,
    overlay_mask,
)
from tests.conftest import FRAME_H, FRAME_W, region_mask, warning_box


def test_all_expected_placements_exist():
    specs = load_placements()
    for name in PLACEMENTS:
        assert name in specs
    assert "reels_with_disclaimer" in specs


def test_zone_figures_are_flagged_unverified():
    """V11 is open. Until it closes, every finding must carry the caveat.

    This test is the guard against quietly shipping secondary numbers as if Meta
    had published them. When V11 closes, flip placements.yaml to
    `status: verified` and this test's expectation with it.
    """
    spec = get_spec("reels")
    assert spec.verified is False
    caveat = spec.caveat()
    assert caveat is not None
    assert "unverified" in caveat


def test_feed_has_no_overlay_zone():
    mask = overlay_mask("feed", FRAME_W, FRAME_H)
    assert not mask.any(), "Feed is the control case — a vacuous pass would hide bugs"


def test_reels_reserves_top_and_bottom():
    mask = overlay_mask("reels", FRAME_W, FRAME_H)
    spec = get_spec("reels")

    assert mask[0, FRAME_W // 2]
    assert mask[-1, FRAME_W // 2]
    # The middle band, away from the side rails, must be clear.
    assert not mask[FRAME_H // 2, FRAME_W // 2]

    top_rows = int(np.ceil(spec.top * FRAME_H))
    assert mask[top_rows - 1, FRAME_W // 2]
    assert not mask[top_rows, FRAME_W // 2]


def test_reels_bottom_zone_is_larger_than_stories():
    reels = overlay_mask("reels", FRAME_W, FRAME_H)
    stories = overlay_mask("stories", FRAME_W, FRAME_H)
    assert reels.sum() > stories.sum()


def test_disclaimer_variant_reserves_more_than_plain_reels():
    plain = overlay_mask("reels", FRAME_W, FRAME_H)
    disclaimed = overlay_mask("reels_with_disclaimer", FRAME_W, FRAME_H)
    assert disclaimed.sum() > plain.sum()


def test_rounding_is_outward():
    """Half a pixel of warning under the caption block is still obscured."""
    mask = overlay_mask("reels", 100, 101)  # 0.14 * 101 = 14.14 -> 15 rows
    assert mask[:15, 50].all()


def test_unknown_placement_is_an_error():
    with pytest.raises(KeyError, match="unknown placement"):
        overlay_mask("tiktok", FRAME_W, FRAME_H)


def test_bad_frame_size_is_an_error():
    with pytest.raises(ValueError, match="bad frame size"):
        overlay_mask("reels", 0, 100)


def test_warning_in_reels_bottom_zone_is_occluded():
    """The demo claim: in Reels, the platform's own buttons cover the warning."""
    mask = region_mask(FRAME_W, FRAME_H, warning_box())

    reels = occlusion(mask, "reels")
    feed = occlusion(mask, "feed")

    assert reels.any_occluded, "the warning sits inside the Reels caption zone"
    assert reels.fraction_bp > 0
    assert not feed.any_occluded, "the same creative is clear in Feed"
    assert reels.verified_spec is False
    assert reels.caveat is not None


def test_occlusion_of_a_safe_region_is_zero():
    safe = region_mask(FRAME_W, FRAME_H, (100, FRAME_H // 2 - 40, 200, 80))
    result = occlusion(safe, "reels")
    assert result.occluded_pixels == 0
    assert result.fraction_bp == 0


def test_fully_occluded_region_reads_10000_bp():
    top_strip = region_mask(FRAME_W, FRAME_H, (100, 0, 200, 20))
    result = occlusion(top_strip, "reels")
    assert result.fraction_bp == 10_000


def test_occlusion_values_are_chain_safe():
    mask = region_mask(FRAME_W, FRAME_H, warning_box())
    result = occlusion(mask, "reels")
    for value in (result.region_pixels, result.occluded_pixels, result.fraction_bp):
        assert isinstance(value, int)
