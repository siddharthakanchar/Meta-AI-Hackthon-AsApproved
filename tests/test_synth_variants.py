"""VariantBench-UK integrity.

A seeded violation that does not actually violate anything when measured is
worse than no benchmark at all: the detector would be scored against a label
that the pixels do not support, and the resulting recall number would be a lie.

So each violating transform is checked against the Phase 2 measurement
primitives — contrast, occlusion, geometry. Note what this is and is not: it
exercises the deterministic measuring code, NOT the rules engine and NOT the
models, so it is dataset validation rather than the detector grading its own
homework.
"""

from __future__ import annotations

import numpy as np
import pytest

from asapproved.measure import detect_border, measure_contrast
from asapproved.synth.specs import MASTERS, prescribed_text
from asapproved.synth.transforms import (
    TRANSFORMS,
    FrameCtx,
    VariantPlan,
    transforms_for,
)
from asapproved.synth.variants import _render_variant_frame, ranges_from_flags
from asapproved.text_norm import same_prescribed_text
from asapproved.vision.overlays import occlusion

STILL_MASTERS = [s for s in MASTERS if s.kind == "still"]


def _plans(masters=MASTERS):
    out = []
    for spec in masters:
        for i, t in enumerate(transforms_for(spec)):
            out.append(VariantPlan(master=spec, transform=t, index=i))
    return out


ALL_PLANS = _plans()


def _mask(box, size):
    w, h = size
    m = np.zeros((h, w), dtype=bool)
    x, y, bw, bh = box
    m[y : y + bh, x : x + bw] = True
    return m


# --------------------------------------------------------------------------
# dataset shape
# --------------------------------------------------------------------------


def test_forty_eight_variants_split_evenly():
    assert len(ALL_PLANS) == 48
    violations = [p for p in ALL_PLANS if not p.transform.benign]
    benign = [p for p in ALL_PLANS if p.transform.benign]
    assert len(violations) == 24
    assert len(benign) == 24


def test_every_master_gets_four_variants():
    for spec in MASTERS:
        assert len([p for p in ALL_PLANS if p.master.id == spec.id]) == 4


def test_variant_ids_are_unique():
    ids = [p.variant_id for p in ALL_PLANS]
    assert len(ids) == len(set(ids))


def test_no_master_gets_the_same_transform_twice():
    for spec in MASTERS:
        names = [p.transform.name for p in ALL_PLANS if p.master.id == spec.id]
        assert len(names) == len(set(names)), f"{spec.id} repeats a transform"


def test_seeded_violations_span_the_rulebook():
    """R1-R12 minus R2, which is settings drift and has no pixel expression.

    Spread matters: 24 violations clustered on three rules would make the
    per-rule precision/recall table in §10 mostly empty, and the headline F1
    would be an average over almost nothing.
    """
    covered = set()
    for plan in ALL_PLANS:
        covered.update(plan.transform.rules)

    expected = {f"R{n}" for n in range(1, 13)} - {"R2"}
    missing = expected - covered
    assert not missing, (
        f"no seeded variant exercises {sorted(missing)} — the per-rule benchmark "
        "would have empty rows"
    )


def test_no_rule_is_covered_by_only_one_variant():
    """A per-rule score computed over one variant can only read 0% or 100%.

    The first allocator guaranteed coverage and stopped there, leaving R1 on ten
    variants and five rules on one each. Five of eleven rows in the §10 per-rule
    table would have been noise presented as measurement.
    """
    counts: dict[str, int] = {}
    for plan in ALL_PLANS:
        for rule in plan.transform.rules:
            counts[rule] = counts.get(rule, 0) + 1

    thin = {r: n for r, n in counts.items() if n < 2}
    assert not thin, f"rules with a single variant: {thin} — per-rule metrics would be noise"


def test_r2_is_deliberately_absent_from_the_pixel_set():
    """R2 is settings drift: manifest vs live API, invisible in the creative.

    Pinned so nobody later "fixes" its absence by inventing a pixel proxy for it.
    """
    assert not any("R2" in t.rules for t in TRANSFORMS)


def test_every_variant_declares_a_meta_enhancement():
    for plan in ALL_PLANS:
        assert plan.transform.enhancement, f"{plan.variant_id} has no enhancement"


def test_audio_only_transforms_are_flagged():
    for t in TRANSFORMS:
        if t.name in {"voiceover_drops_apr", "music_swap"}:
            assert t.requires_audio
            assert t.frame_fn is None and t.layout_fn is None


# --------------------------------------------------------------------------
# the seeded violations must actually violate
# --------------------------------------------------------------------------


def _render(plan: VariantPlan):
    rendered = _render_variant_frame(plan.master, plan.transform, 0)
    ctx = FrameCtx(spec=plan.master, regions=dict(rendered.regions), size=plan.master.size)
    bgr = rendered.to_bgr()
    if plan.transform.frame_fn:
        bgr = plan.transform.frame_fn(bgr, 0, plan.master.total_frames, ctx)
    return rendered, bgr, ctx


def _plans_named(name: str):
    return [p for p in ALL_PLANS if p.transform.name == name]


@pytest.mark.parametrize(
    "plan", _plans_named("warning_low_contrast"), ids=lambda p: p.master.id
)
def test_low_contrast_variant_really_is_below_threshold(plan):
    rendered, bgr, _ = _render(plan)
    mask = _mask(rendered.regions["warning"], plan.master.size)
    ratio = measure_contrast(bgr, mask)
    assert ratio is not None, "contrast should still be measurable, just bad"
    assert ratio < 450, f"{plan.variant_id}: {ratio / 100:.2f}:1 is not below 4.5:1"


@pytest.mark.parametrize(
    "plan", _plans_named("warning_border_removed"), ids=lambda p: p.master.id
)
def test_border_removed_variant_really_has_no_border(plan):
    rendered, bgr, _ = _render(plan)
    assert detect_border(bgr, rendered.regions["warning"]) is False


@pytest.mark.parametrize(
    "plan", _plans_named("warning_into_overlay_zone"), ids=lambda p: p.master.id
)
def test_overlay_zone_variant_really_is_occluded(plan):
    """R12's threshold is any occluded pixel; verify there genuinely are some."""
    rendered, _, _ = _render(plan)
    mask = _mask(rendered.regions["warning"], plan.master.size)
    placement = (
        "reels_with_disclaimer" if plan.master.placement == "reels" else plan.master.placement
    )
    result = occlusion(mask, placement)
    assert result.occluded_pixels > 0, (
        f"{plan.variant_id}: warning is NOT inside the {placement} UI zone, "
        "so the R12 label is unsupported"
    )


@pytest.mark.parametrize("plan", _plans_named("warning_shrunk"), ids=lambda p: p.master.id)
def test_shrunk_warning_is_smaller_than_the_master_warning(plan):
    master_rendered = _render_variant_frame(plan.master, _benign_noop(), 0)
    variant_rendered, _, _ = _render(plan)
    assert variant_rendered.regions["warning"][3] < master_rendered.regions["warning"][3]


@pytest.mark.parametrize(
    "plan", _plans_named("apr_shrunk_below_trigger"), ids=lambda p: p.master.id
)
def test_shrunk_apr_is_less_prominent_than_its_trigger(plan):
    rendered, _, _ = _render(plan)
    assert rendered.regions["apr"][3] < rendered.regions["trigger"][3]


@pytest.mark.parametrize("plan", _plans_named("warning_reworded"), ids=lambda p: p.master.id)
def test_reworded_warning_no_longer_matches_prescribed_text(plan):
    reworded = plan.transform.text_fn(plan.master)
    original = prescribed_text(plan.master.investment_type)
    assert not same_prescribed_text(reworded, original)


@pytest.mark.parametrize(
    "plan", _plans_named("representative_example_removed"), ids=lambda p: p.master.id
)
def test_removed_example_leaves_the_cost_figures_behind(plan):
    """R10 is 'a cost-of-credit figure with no representative example'.

    If the APR line vanished along with the example there would be no trigger
    left and the variant would be compliant-but-empty, not a violation.
    """
    rendered, _, _ = _render(plan)
    assert "warning" not in rendered.regions
    assert "apr" in rendered.regions and "trigger" in rendered.regions


@pytest.mark.parametrize(
    "plan",
    [p for p in ALL_PLANS if p.transform.name in {"crop_removes_warning", "zoom_drops_warning", "expand_pushes_warning_offframe"}],
    ids=lambda p: f"{p.master.id}-{p.transform.name}",
)
def test_geometry_violations_really_remove_the_warning(plan):
    """The bug the generator's cross-check caught, pinned as a test.

    A fixed 1.4x zoom dropped a Feed warning at 80% of the frame and left a
    Reels warning at 45% fully visible, while the label claimed removal either
    way. The scale is now derived from where the warning actually sits.
    """
    rendered, _, ctx = _render(plan)
    box = rendered.regions.get("warning")
    assert box is not None

    mask3 = np.zeros((*plan.master.size[::-1], 3), dtype=np.uint8)
    x, y, w, h = box
    mask3[y : y + h, x : x + w] = 255
    moved = plan.transform.frame_fn(mask3, 0, plan.master.total_frames, ctx)
    surviving = int((moved[..., 0] > 127).sum())
    original = w * h
    assert surviving < original * 0.02, (
        f"{plan.variant_id}: {surviving / original:.0%} of the warning survives the "
        "transform, so the R3 label is unsupported"
    )


# --------------------------------------------------------------------------
# the benign edits must stay benign
# --------------------------------------------------------------------------


def _benign_noop():
    return next(t for t in TRANSFORMS if t.name == "brightness_lift")


@pytest.mark.parametrize(
    "plan",
    [p for p in ALL_PLANS if p.transform.benign and p.transform.frame_fn and p.master.kind == "still"],
    ids=lambda p: f"{p.master.id}-{p.transform.name}",
)
def test_benign_edits_leave_the_warning_legible(plan):
    """A 'benign' variant that broke the warning would poison the false-block rate.

    The false-block number is the one a compliance buyer actually cares about —
    a tool that blocks good ads is unusable — so the benign half of the set has
    to be genuinely benign.
    """
    rendered, bgr, ctx = _render(plan)
    box = rendered.regions["warning"]

    mask3 = np.zeros((*plan.master.size[::-1], 3), dtype=np.uint8)
    x, y, w, h = box
    mask3[y : y + h, x : x + w] = 255
    moved = plan.transform.frame_fn(mask3, 0, plan.master.total_frames, ctx)
    surviving = int((moved[..., 0] > 127).sum())
    assert surviving > w * h * 0.90, f"{plan.variant_id} lost {1 - surviving / (w * h):.0%} of the warning"

    ys, xs = np.nonzero(moved[..., 0] > 127)
    sub = np.zeros(bgr.shape[:2], dtype=bool)
    sub[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] = True
    ratio = measure_contrast(bgr, sub)
    assert ratio is not None and ratio >= 450, (
        f"{plan.variant_id}: a benign edit dropped warning contrast to "
        f"{(ratio or 0) / 100:.2f}:1"
    )


# --------------------------------------------------------------------------
# label plumbing
# --------------------------------------------------------------------------


def test_ranges_from_flags():
    assert ranges_from_flags([]) == []
    assert ranges_from_flags([False, False]) == []
    assert ranges_from_flags([True, True, True]) == [[0, 2]]
    assert ranges_from_flags([True, False, True, True]) == [[0, 0], [2, 3]]
    assert ranges_from_flags([False, True, False]) == [[1, 1]]
