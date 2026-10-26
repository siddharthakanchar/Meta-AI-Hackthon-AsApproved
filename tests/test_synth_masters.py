"""The masters must be compliant by construction.

They are the baseline that "approved" means. A master that quietly breached a
rule would make every measurement taken against it meaningless, and would show up
in the benchmark as the detector's fault rather than the data's.
"""

from __future__ import annotations

import numpy as np
import pytest

from asapproved.measure import measure_region
from asapproved.synth.build import compliant_layout, render_master_frame
from asapproved.synth.specs import MASTERS, prescribed_text
from asapproved.text_norm import same_prescribed_text
from asapproved.vision.overlays import occlusion

STILLS = [s for s in MASTERS if s.kind == "still"]
# Rendering one frame of each video is enough — a master's layout is constant.
ONE_FRAME = MASTERS


def _mask_for(box, size):
    w, h = size
    mask = np.zeros((h, w), dtype=bool)
    x, y, bw, bh = box
    mask[y : y + bh, x : x + bw] = True
    return mask


def test_twelve_masters_in_the_right_mix():
    assert len(MASTERS) == 12
    stills = [s for s in MASTERS if s.kind == "still"]
    videos = [s for s in MASTERS if s.kind == "video"]
    assert len(stills) == 7 and len(videos) == 5

    credit_stills = [s for s in stills if s.is_credit]
    investment_stills = [s for s in stills if not s.is_credit]
    credit_videos = [s for s in videos if s.is_credit]
    investment_videos = [s for s in videos if not s.is_credit]
    assert len(credit_stills) == 5
    assert len(credit_videos) == 3
    assert len(investment_stills) == 2
    assert len(investment_videos) == 2


def test_all_four_prescribed_warnings_are_exercised():
    """R11 has four texts; the dataset must cover all of them, not just crypto."""
    used = {s.investment_type for s in MASTERS if s.investment_type}
    assert used == {
        "cryptoassets",
        "non_readily_realisable_securities",
        "p2p_agreements",
        "long_term_asset_fund",
    }


def test_master_ids_are_unique():
    ids = [s.id for s in MASTERS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("spec", ONE_FRAME, ids=lambda s: s.id)
def test_investment_masters_carry_the_exact_prescribed_text(spec):
    if spec.is_credit:
        assert "APR" in spec.warning_text, "a credit master needs a representative example"
        return
    assert same_prescribed_text(spec.warning_text, prescribed_text(spec.investment_type))


@pytest.mark.parametrize("spec", ONE_FRAME, ids=lambda s: s.id)
def test_warning_sits_outside_the_placement_overlay_zone(spec):
    """R12 on the baseline must be clean, or R12 on variants means nothing.

    This is the regression guard for the bug found while rendering: the default
    warning position sat inside the Reels caption block, so every Reels master
    breached the rule it was meant to be the clean comparison for.
    """
    rendered = render_master_frame(spec)
    box = rendered.regions["warning"]
    mask = _mask_for(box, spec.size)

    placement = "reels_with_disclaimer" if spec.placement == "reels" else spec.placement
    result = occlusion(mask, placement)
    assert result.occluded_pixels == 0, (
        f"{spec.id}: warning overlaps the {placement} UI zone by "
        f"{result.fraction_bp / 100:.1f}% — the master is not a compliant baseline"
    )


@pytest.mark.parametrize("spec", ONE_FRAME, ids=lambda s: s.id)
def test_warning_is_bordered_and_high_contrast(spec):
    """COBS 4.12A.36R: own border, legible. Measured, not assumed."""
    rendered = render_master_frame(spec)
    frame = rendered.to_bgr()
    mask = _mask_for(rendered.regions["warning"], spec.size)

    m = measure_region(frame, mask, "warning", placement=None)
    assert m.border_present is True, f"{spec.id}: no border detected on the warning box"
    assert m.contrast_x100 is not None, f"{spec.id}: contrast unmeasurable"
    assert m.contrast_x100 >= 450, (
        f"{spec.id}: warning contrast {m.contrast_x100 / 100:.1f}:1 is below the 4.5:1 "
        "threshold the rulebook uses"
    )


@pytest.mark.parametrize("spec", [s for s in MASTERS if s.is_credit], ids=lambda s: s.id)
def test_apr_is_no_less_prominent_than_its_trigger(spec):
    """CONC 3.5.7R, measured on the pixels rather than asserted in a comment."""
    rendered = render_master_frame(spec)
    trigger = rendered.regions["trigger"]
    apr = rendered.regions["apr"]

    assert apr[3] >= trigger[3], f"{spec.id}: APR is shorter than the trigger"
    # Adjacent, not buried further down the creative.
    assert 0 < apr[1] - trigger[1] < spec.size[1] * 0.12


@pytest.mark.parametrize("spec", ONE_FRAME, ids=lambda s: s.id)
def test_warning_is_not_clipped_and_regions_are_in_frame(spec):
    rendered = render_master_frame(spec)
    w, h = spec.size
    for label, (x, y, bw, bh) in rendered.regions.items():
        assert x >= 0 and y >= 0, f"{spec.id}/{label} starts off-frame"
        assert x + bw <= w, f"{spec.id}/{label} runs off the right edge by {x + bw - w}px"
        assert y + bh <= h, f"{spec.id}/{label} runs off the bottom by {y + bh - h}px"


@pytest.mark.parametrize("spec", ONE_FRAME, ids=lambda s: s.id)
def test_no_two_regions_overlap(spec):
    """Regions are ground truth, so two of them claiming the same pixels is a
    data-integrity bug, not a cosmetic one.

    Caught the real case: bottom-aligning the warning inside the narrow Reels
    band dropped the white box straight onto the APR line. R8 compares APR and
    trigger prominence and SAM is scored on region IoU — both would have been
    measured against overlapping truth.
    """
    rendered = render_master_frame(spec)
    items = sorted(rendered.regions.items())
    for i, (label_a, a) in enumerate(items):
        for label_b, b in items[i + 1 :]:
            ax, ay, aw, ah = a
            bx, by, bw, bh = b
            overlap_w = min(ax + aw, bx + bw) - max(ax, bx)
            overlap_h = min(ay + ah, by + bh) - max(ay, by)
            if overlap_w > 0 and overlap_h > 0:
                area = overlap_w * overlap_h
                smaller = min(aw * ah, bw * bh)
                # A couple of stray pixels of leading is tolerable; a real
                # collision is not.
                assert area < smaller * 0.02, (
                    f"{spec.id}: '{label_a}' and '{label_b}' overlap by "
                    f"{overlap_w}x{overlap_h}px ({area / smaller:.0%} of the smaller region)"
                )


@pytest.mark.parametrize("spec", ONE_FRAME, ids=lambda s: s.id)
def test_investment_masters_have_no_apr_region(spec):
    """An investment promotion has no representative APR; asserting one would
    give R8 a region to score against on a master where it does not apply."""
    rendered = render_master_frame(spec)
    if spec.is_credit:
        assert "apr" in rendered.regions and "risk_note" not in rendered.regions
    else:
        assert "risk_note" in rendered.regions and "apr" not in rendered.regions


def test_compliant_layout_narrows_the_band_for_reels():
    reels = next(s for s in MASTERS if s.placement == "reels")
    feed = next(s for s in MASTERS if s.placement == "feed")
    assert compliant_layout(reels).safe_bottom < compliant_layout(feed).safe_bottom
    assert compliant_layout(reels).safe_top > compliant_layout(feed).safe_top


@pytest.mark.parametrize("spec", ONE_FRAME, ids=lambda s: s.id)
def test_small_print_also_stays_out_of_the_overlay_zone(spec):
    """Our own SIMULATED disclosure has to survive the placement too.

    Not pedantry: the small print is the label that tells a viewer this is
    synthetic, and a tool that measures whether disclosures survive platform
    chrome should not lose its own to the caption block.
    """
    rendered = render_master_frame(spec)
    mask = _mask_for(rendered.regions["small_print"], spec.size)
    placement = "reels_with_disclaimer" if spec.placement == "reels" else spec.placement
    assert occlusion(mask, placement).occluded_pixels == 0, f"{spec.id}: small print is occluded"
