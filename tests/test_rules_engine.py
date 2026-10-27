"""C8 — one test per rule, and the behaviour that matters most across all of them:
an input we could not measure produces `inconclusive`, never a pass and never a fail.

A pass on unknown input waves through a real breach. A fail on unknown input
accuses an advertiser on a guess. Both are worse than saying "I don't know", and
neither is acceptable in something a compliance officer signs off against.
"""

from __future__ import annotations

import pytest

from asapproved.rules.engine import (
    Context,
    evaluate,
    load_rulebook,
    summarise,
)


def _ctx(**kw) -> Context:
    base = {
        "variant_id": "v1",
        "master_id": "m1",
        "placement": "feed",
        "alignment_ok": True,
        "master_regions": {"warning": {"present": True, "bbox": [10, 10, 100, 40]}},
        "variant_regions": {"warning": {"present": True, "bbox": [10, 10, 100, 40]}},
    }
    base.update(kw)
    return Context(**base)


def _find(findings, rule_id):
    return next(f for f in findings if f.rule_id == rule_id)


# --------------------------------------------------------------------------
# rulebook loading
# --------------------------------------------------------------------------


def test_rulebook_loads_all_rules():
    book = load_rulebook()
    assert book.version == "uk_v1"
    assert [r.id for r in book.rules] == [f"R{n}" for n in range(1, 13)] + ["B1"]


def test_thresholds_are_converted_to_integer_units():
    """0.02 must become 200 basis points and 4.5 must become 450.

    Comparing a 4.5 against a 450 would silently pass every contrast check in the
    suite, so the conversion lives in the loader and is pinned here.
    """
    book = load_rulebook()
    assert book.rule("R1").threshold == 200
    assert book.rule("R1").threshold_display == "2%"
    assert book.rule("R4").threshold == 9800
    assert book.rule("R6").threshold == 450
    assert book.rule("R6").threshold_display == "4.5:1"
    assert book.rule("R12").threshold == 0


def test_rulebook_is_still_draft_and_says_so():
    """Until the citations are re-checked (V9/V10), `verified` must stay False."""
    book = load_rulebook()
    assert book.verified is False


# --------------------------------------------------------------------------
# R1 — material change inside a claim region
# --------------------------------------------------------------------------


def test_r1_fails_above_threshold():
    f = _find(evaluate(_ctx(changed_in_region_bp={"warning": 450})), "R1")
    assert f.status == "fail"
    assert f.measured == 450
    assert "4.5%" in f.detail


def test_r1_passes_below_threshold():
    f = _find(evaluate(_ctx(changed_in_region_bp={"warning": 120})), "R1")
    assert f.status == "pass"


def test_r1_is_inconclusive_when_alignment_failed():
    """The C3 trust gate: unreliable geometry must not produce a confident verdict."""
    f = _find(
        evaluate(
            _ctx(
                alignment_ok=False,
                alignment_note="only 4 matches; fell back to scale-only",
                changed_in_region_bp={"warning": 9000},
            )
        ),
        "R1",
    )
    assert f.status == "inconclusive"
    assert "could not be aligned" in f.detail
    assert "alignment failed" in f.caveats


# --------------------------------------------------------------------------
# R2 — settings drift
# --------------------------------------------------------------------------


def test_r2_fails_when_an_enhancement_was_switched_on():
    f = _find(
        evaluate(
            _ctx(
                manifest_settings={"image_animation": "OPT_OUT", "image_touchups": "OPT_OUT"},
                live_settings={"image_animation": "OPT_IN", "image_touchups": "OPT_OUT"},
            )
        ),
        "R2",
    )
    assert f.status == "fail"
    assert f.severity == "block"
    assert "image_animation" in f.detail


def test_r2_passes_when_settings_match():
    f = _find(
        evaluate(
            _ctx(
                manifest_settings={"image_animation": "OPT_OUT"},
                live_settings={"image_animation": "OPT_OUT"},
            )
        ),
        "R2",
    )
    assert f.status == "pass"


def test_r2_without_a_snapshot_is_inconclusive_not_pass():
    """No approval-time settings means drift is unknowable, not absent."""
    f = _find(evaluate(_ctx(live_settings={"image_animation": "OPT_IN"})), "R2")
    assert f.status == "inconclusive"


def test_r2_without_live_settings_is_inconclusive():
    f = _find(evaluate(_ctx(manifest_settings={"image_animation": "OPT_OUT"})), "R2")
    assert f.status == "inconclusive"


# --------------------------------------------------------------------------
# R3 — warning removed or clipped
# --------------------------------------------------------------------------


def test_r3_fails_when_the_warning_is_gone():
    f = _find(evaluate(_ctx(variant_regions={"warning": {"present": False}})), "R3")
    assert f.status == "fail"
    assert "absent" in f.detail


def test_r3_fails_when_the_warning_is_clipped():
    f = _find(
        evaluate(
            _ctx(
                variant_regions={
                    "warning": {"present": True, "clipped": True, "bbox": [0, 0, 50, 20]}
                }
            )
        ),
        "R3",
    )
    assert f.status == "fail"
    assert "truncated" in f.detail


def test_r3_not_applicable_when_the_master_had_no_warning():
    f = _find(
        evaluate(
            _ctx(
                master_regions={"warning": {"present": False}},
                variant_regions={"warning": {"present": False}},
            )
        ),
        "R3",
    )
    assert f.status == "not_applicable"


# --------------------------------------------------------------------------
# R4 — on screen throughout
# --------------------------------------------------------------------------


def test_r4_fails_below_the_ratio():
    f = _find(
        evaluate(
            _ctx(
                is_video=True,
                fps=25,
                visible_ratio_bp={"warning": 800},
                longest_gap_frames={"warning": 345},
            )
        ),
        "R4",
    )
    assert f.status == "fail"
    assert "8.0%" in f.detail
    assert "13.8s" in f.detail  # the gap, which the ratio alone cannot convey


def test_r4_passes_when_on_screen_throughout():
    f = _find(evaluate(_ctx(is_video=True, fps=25, visible_ratio_bp={"warning": 10000})), "R4")
    assert f.status == "pass"


def test_r4_not_applicable_to_stills():
    assert _find(evaluate(_ctx(is_video=False)), "R4").status == "not_applicable"


# --------------------------------------------------------------------------
# R5 — border, bold, underline
# --------------------------------------------------------------------------


def test_r5_fails_when_a_sub_check_fails():
    f = _find(
        evaluate(
            _ctx(
                variant_regions={
                    "warning": {
                        "present": True,
                        "border_present": False,
                        "bold_present": True,
                        "underline_present": True,
                    }
                }
            )
        ),
        "R5",
    )
    assert f.status == "fail"
    assert f.sub_results == {"border": "fail", "bold": "pass", "underline": "pass"}


def test_r5_will_not_pass_a_conjunction_it_only_partly_measured():
    """COBS 4.12A.36R is border AND bold AND underline.

    This previously returned `pass` with two of three limbs unmeasured — which
    asserted compliance with a rule we had checked a third of, and contradicted
    this engine's own invariant that an unknown input never yields a pass. The
    pipeline hard-codes bold and underline as unmeasurable (V14), so that pass
    was the verdict on EVERY run. Unknown is still not a breach: the answer is
    inconclusive, not fail.
    """
    f = _find(
        evaluate(
            _ctx(
                variant_regions={
                    "warning": {
                        "present": True,
                        "border_present": True,
                        "bold_present": None,
                        "underline_present": None,
                    }
                }
            )
        ),
        "R5",
    )
    assert f.status == "inconclusive"
    assert f.sub_results["border"] == "pass"
    assert f.sub_results["bold"] == "inconclusive"
    assert "bold not measurable" in f.caveats
    assert "requires all of them" in f.detail


def test_r5_is_inconclusive_when_nothing_could_be_measured():
    f = _find(
        evaluate(
            _ctx(
                variant_regions={
                    "warning": {
                        "present": True,
                        "border_present": None,
                        "bold_present": None,
                        "underline_present": None,
                    }
                }
            )
        ),
        "R5",
    )
    assert f.status == "inconclusive"


# --------------------------------------------------------------------------
# R6 — contrast
# --------------------------------------------------------------------------


def test_r6_fails_below_four_point_five():
    f = _find(
        evaluate(_ctx(variant_regions={"warning": {"present": True, "contrast_x100": 310}})),
        "R6",
    )
    assert f.status == "fail"
    assert "3.10:1" in f.detail


def test_r6_passes_at_the_threshold():
    f = _find(
        evaluate(_ctx(variant_regions={"warning": {"present": True, "contrast_x100": 450}})),
        "R6",
    )
    assert f.status == "pass"


def test_r6_carries_the_engineering_proxy_caveat():
    """The 4.5:1 figure is ours, not the FCA's, and every finding must say so."""
    f = _find(
        evaluate(_ctx(variant_regions={"warning": {"present": True, "contrast_x100": 310}})),
        "R6",
    )
    assert any("engineering proxy" in c for c in f.caveats)


def test_r6_is_inconclusive_when_contrast_cannot_be_measured():
    f = _find(
        evaluate(_ctx(variant_regions={"warning": {"present": True, "contrast_x100": None}})),
        "R6",
    )
    assert f.status == "inconclusive"


# --------------------------------------------------------------------------
# R7 — warning smaller than body copy
# --------------------------------------------------------------------------


def test_r7_fails_when_warning_is_smaller_than_body():
    f = _find(
        evaluate(
            _ctx(
                variant_regions={
                    "warning": {"present": True, "text_height": 11},
                    "body": {"present": True, "text_height": 18},
                }
            )
        ),
        "R7",
    )
    assert f.status == "fail"
    assert "11px" in f.detail and "18px" in f.detail


def test_r7_passes_when_warning_is_larger():
    f = _find(
        evaluate(
            _ctx(
                variant_regions={
                    "warning": {"present": True, "text_height": 22},
                    "body": {"present": True, "text_height": 18},
                }
            )
        ),
        "R7",
    )
    assert f.status == "pass"


def test_r7_is_inconclusive_without_a_body_baseline():
    f = _find(
        evaluate(_ctx(variant_regions={"warning": {"present": True, "text_height": 11}})),
        "R7",
    )
    assert f.status == "inconclusive"


# --------------------------------------------------------------------------
# R8 — APR prominence parity
# --------------------------------------------------------------------------


def test_r8_fails_when_apr_is_smaller_than_the_trigger():
    f = _find(
        evaluate(
            _ctx(
                variant_regions={
                    "apr": {"present": True, "text_height": 14},
                    "trigger": {"present": True, "text_height": 34},
                }
            )
        ),
        "R8",
    )
    assert f.status == "fail"
    assert "14px" in f.detail and "34px" in f.detail


def test_r8_fails_when_the_apr_is_missing_entirely():
    f = _find(
        evaluate(
            _ctx(
                variant_regions={
                    "apr": {"present": False},
                    "trigger": {"present": True, "text_height": 34},
                }
            )
        ),
        "R8",
    )
    assert f.status == "fail"
    assert "absent" in f.detail


def test_r8_catches_time_based_disparity_on_video():
    """The hero case: equal size, wildly unequal time on screen."""
    f = _find(
        evaluate(
            _ctx(
                is_video=True,
                fps=25,
                variant_regions={
                    "apr": {"present": True, "text_height": 34},
                    "trigger": {"present": True, "text_height": 34},
                },
                visible_ratio_bp={"apr": 800, "trigger": 10000},
            )
        ),
        "R8",
    )
    assert f.status == "fail"
    assert "8.0%" in f.detail and "100.0%" in f.detail


def test_r8_not_applicable_to_investment_promotions():
    f = _find(evaluate(_ctx(apr_label="risk_note", investment_type="cryptoassets")), "R8")
    assert f.status == "not_applicable"


# --------------------------------------------------------------------------
# R9 — spoken parity
# --------------------------------------------------------------------------


def test_r9_fails_when_trigger_spoken_but_apr_not():
    f = _find(evaluate(_ctx(is_video=True, trigger_spoken=True, apr_spoken=False)), "R9")
    assert f.status == "fail"


def test_r9_passes_when_both_spoken():
    f = _find(evaluate(_ctx(is_video=True, trigger_spoken=True, apr_spoken=True)), "R9")
    assert f.status == "pass"


def test_r9_without_a_transcript_is_inconclusive_not_pass():
    """Four benchmark variants have no audio yet. They must not score as passes."""
    f = _find(evaluate(_ctx(is_video=True)), "R9")
    assert f.status == "inconclusive"
    assert "no audio transcript" in f.caveats


def test_r9_not_applicable_when_the_trigger_is_not_spoken():
    f = _find(evaluate(_ctx(is_video=True, trigger_spoken=False, apr_spoken=False)), "R9")
    assert f.status == "not_applicable"


# --------------------------------------------------------------------------
# R10 — representative example
# --------------------------------------------------------------------------


def test_r10_fails_when_cost_figures_have_no_example():
    f = _find(
        evaluate(_ctx(cost_of_credit_present=True, representative_example_present=False)),
        "R10",
    )
    assert f.status == "fail"


def test_r10_passes_with_an_example():
    f = _find(
        evaluate(_ctx(cost_of_credit_present=True, representative_example_present=True)),
        "R10",
    )
    assert f.status == "pass"


def test_r10_is_inconclusive_without_claim_extraction():
    assert _find(evaluate(_ctx()), "R10").status == "inconclusive"


# --------------------------------------------------------------------------
# R11 — prescribed wording
# --------------------------------------------------------------------------

CRYPTO = (
    "Don't invest unless you're prepared to lose all the money you invest. This is a "
    "high-risk investment and you should not expect to be protected if something goes wrong."
)


def test_r11_passes_on_exact_prescribed_wording():
    f = _find(evaluate(_ctx(investment_type="cryptoassets", warning_text_variant=CRYPTO)), "R11")
    assert f.status == "pass"


def test_r11_passes_through_typographic_apostrophes():
    curly = CRYPTO.replace("'", "’")
    f = _find(evaluate(_ctx(investment_type="cryptoassets", warning_text_variant=curly)), "R11")
    assert f.status == "pass", "a re-typeset apostrophe is not an altered warning"


def test_r11_fails_on_the_nrrs_wording_used_for_crypto():
    """The five-word difference that justifies the per-type table (D-007)."""
    nrrs = CRYPTO.replace("you should not expect to be", "you are unlikely to be")
    f = _find(evaluate(_ctx(investment_type="cryptoassets", warning_text_variant=nrrs)), "R11")
    assert f.status == "fail"
    assert "diverges at word" in f.detail


def test_r11_not_applicable_to_credit_promotions():
    assert _find(evaluate(_ctx(warning_text_variant="anything")), "R11").status == "not_applicable"


def test_r11_is_inconclusive_when_text_could_not_be_read():
    f = _find(evaluate(_ctx(investment_type="cryptoassets")), "R11")
    assert f.status == "inconclusive"


# --------------------------------------------------------------------------
# R12 — placement overlay
# --------------------------------------------------------------------------


def test_r12_fails_on_any_occluded_pixel():
    f = _find(evaluate(_ctx(placement="reels", occluded_pixels={"warning": 1})), "R12")
    assert f.status == "fail"


def test_r12_passes_when_clear():
    f = _find(evaluate(_ctx(placement="reels", occluded_pixels={"warning": 0})), "R12")
    assert f.status == "pass"


def test_r12_carries_the_unverified_zone_caveat():
    """V11 is open: the zone percentages are secondary, not Meta's own."""
    f = _find(
        evaluate(
            _ctx(
                placement="reels",
                occluded_pixels={"warning": 500},
                occlusion_caveats=["Safe-zone figures for 'reels' are unverified"],
            )
        ),
        "R12",
    )
    assert f.status == "fail"
    assert any("unverified" in c for c in f.caveats)


def test_r12_is_inconclusive_without_a_placement():
    assert _find(evaluate(_ctx(placement=None)), "R12").status == "inconclusive"


# --------------------------------------------------------------------------
# B1 — TV benchmark
# --------------------------------------------------------------------------


def test_b1_is_benchmark_only_and_never_blocks():
    f = _find(
        evaluate(_ctx(is_video=True, warning_word_count=24, warning_seconds_visible=2.0)), "B1"
    )
    assert f.status == "fail"
    assert f.benchmark_only is True
    assert f.blocking is False
    assert any("not the legal test" in c for c in f.caveats)


def test_b1_hold_time_formula():
    """0.2s/word + 2s, +3s at 10 words or more."""
    f = _find(
        evaluate(_ctx(is_video=True, warning_word_count=10, warning_seconds_visible=99.0)), "B1"
    )
    assert f.threshold_display == "7.0s"  # 0.2*10 + 2 + 3
    assert f.status == "pass"


# --------------------------------------------------------------------------
# cross-cutting
# --------------------------------------------------------------------------


def test_an_empty_context_never_produces_a_fail():
    """The single most important property in the engine.

    With nothing measured, every rule must abstain. If any rule can fail on an
    empty context it is asserting something it did not observe.
    """
    findings = evaluate(Context())
    failures = [f.rule_id for f in findings if f.status == "fail"]
    assert not failures, f"rules failed on an empty context: {failures}"


def test_every_rule_produces_exactly_one_finding():
    findings = evaluate(_ctx())
    book = load_rulebook()
    assert len(findings) == len(book.rules)
    assert len({f.rule_id for f in findings}) == len(book.rules)


def test_every_finding_carries_its_citation_and_the_not_legal_advice_flag():
    for f in evaluate(_ctx()):
        assert f.citation
        assert f.paraphrase
        assert f.not_legal_advice is True
        assert f.rulebook_version == "uk_v1"


def test_benchmark_only_findings_are_excluded_from_the_failure_count():
    findings = evaluate(_ctx(is_video=True, warning_word_count=24, warning_seconds_visible=1.0))
    summary = summarise(findings)
    assert "B1" not in summary["failed_rules"]


def test_findings_are_chain_safe():
    from asapproved.canonical import assert_no_floats

    for f in evaluate(_ctx(changed_in_region_bp={"warning": 450})):
        assert_no_floats(f.to_record())


@pytest.mark.parametrize("rule_id", [f"R{n}" for n in range(1, 13)])
def test_no_rule_claims_a_pass_on_an_empty_context(rule_id):
    f = _find(evaluate(Context()), rule_id)
    assert f.status in {
        "inconclusive",
        "not_applicable",
    }, f"{rule_id} returned '{f.status}' with nothing measured"


# --------------------------------------------------------------------------
# R12 asymmetry: a breach is conclusive, "clear" needs completeness
# --------------------------------------------------------------------------


def test_r12_measured_breach_is_conclusive_even_if_another_region_is_unmeasured():
    """Finding occlusion settles the question; not finding it does not.

    This returned `inconclusive` over a region plainly measured as 57,600
    pixels occluded, because a second region could not be measured. Evidence of
    a breach does not become uncertain when something else is unknown.
    """
    f = _find(
        evaluate(
            _ctx(
                placement="reels",
                apr_label="risk_note",
                investment_type="cryptoassets",
                occluded_pixels={"risk_note": 57600},
                variant_regions={
                    "risk_note": {"present": True, "bbox": [50, 1100, 600, 120]},
                    "warning": {"present": False, "locate_confident": True},
                },
            )
        ),
        "R12",
    )
    assert f.status == "fail"


def test_r12_clear_verdict_requires_every_watched_region():
    """The converse: "no occlusion" must not be claimed over an unmeasured region."""
    f = _find(
        evaluate(
            _ctx(
                placement="reels",
                occluded_pixels={"warning": 0},
                variant_regions={
                    "warning": {"present": True, "bbox": [50, 100, 600, 120]},
                    "apr": {"present": True, "bbox": [50, 300, 400, 40]},
                },
            )
        ),
        "R12",
    )
    assert f.status == "inconclusive"
    assert "apr" in f.detail


def test_r12_small_overlap_on_an_inferred_box_is_inconclusive():
    """A box we predicted rather than matched carries localisation error.

    Measured on VariantBench-UK: genuine occlusions cover 40-64% of the region,
    while false positives from alignment-predicted boxes covered 0.6-9.5%. The
    side bands are only ~6% of frame width, so a small overlap on an inferred
    box is indistinguishable from our own error.
    """
    f = _find(
        evaluate(
            _ctx(
                placement="reels",
                occluded_pixels={"warning": 900},
                variant_regions={
                    "warning": {
                        "present": True,
                        "bbox": [0, 100, 600, 120],
                        "located_by": "alignment",
                    }
                },
            )
        ),
        "R12",
    )
    assert f.status == "inconclusive"
    assert "inferred rather than matched" in f.detail


def test_r12_large_overlap_fails_even_on_an_inferred_box():
    f = _find(
        evaluate(
            _ctx(
                placement="reels",
                occluded_pixels={"warning": 50000},
                variant_regions={
                    "warning": {
                        "present": True,
                        "bbox": [0, 100, 600, 120],
                        "located_by": "alignment",
                    }
                },
            )
        ),
        "R12",
    )
    assert f.status == "fail"


def test_r12_any_pixel_still_fails_on_a_matched_box():
    """The rulebook threshold is unchanged for a region we actually matched."""
    f = _find(
        evaluate(
            _ctx(
                placement="reels",
                occluded_pixels={"warning": 1},
                variant_regions={
                    "warning": {
                        "present": True,
                        "bbox": [0, 100, 600, 120],
                        "located_by": "template",
                    }
                },
            )
        ),
        "R12",
    )
    assert f.status == "fail"
