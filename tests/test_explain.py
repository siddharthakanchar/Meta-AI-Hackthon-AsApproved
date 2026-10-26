"""C10 — the explanation validator, tested adversarially.

These are not tests of a model. They are tests of the guard that stands between a
model and a compliance record, written against the specific ways fluent text goes
wrong: a plausible number nobody measured, a rule that never ran, an invented
quotation, a citation recalled from training rather than from the rulebook.

The validator is pure, so every one of these is deterministic.
"""

from __future__ import annotations

import pytest

from asapproved.explain import (
    build_prompt,
    evidence_bundle,
    template_note,
    validate_note,
    write_note,
)
from asapproved.rules.engine import Context, evaluate


def _findings():
    ctx = Context(
        variant_id="v1",
        master_id="m1",
        is_video=True,
        fps=25,
        placement="reels",
        visible_ratio_bp={"warning": 800, "trigger": 10000, "apr": 800},
        longest_gap_frames={"warning": 345},
        variant_regions={
            "warning": {"present": True, "bbox": [40, 900, 640, 110], "contrast_x100": 310},
            "apr": {"present": True, "text_height": 14},
            "trigger": {"present": True, "text_height": 34},
        },
        master_regions={"warning": {"present": True, "bbox": [40, 900, 640, 110]}},
        occluded_pixels={"warning": 12050},
    )
    return evaluate(ctx)


FINDINGS = _findings()


# --------------------------------------------------------------------------
# the validator must accept correct notes
# --------------------------------------------------------------------------


def test_template_note_always_validates():
    """The fallback must never be rejected by the guard that produced it."""
    note = template_note(FINDINGS)
    result = validate_note(note, FINDINGS)
    assert result.ok, result.violations


def test_a_note_using_only_measured_figures_passes():
    note = (
        "The warning is on screen for 8.0% of frames, below the 98% expected. "
        "R4 and R6 failed. Not legal advice."
    )
    assert validate_note(note, FINDINGS).ok


# --------------------------------------------------------------------------
# ...and reject fabrication
# --------------------------------------------------------------------------


def test_rejects_an_invented_number():
    """The classic failure: a fluent, plausible, unmeasured figure."""
    note = "The warning is visible for just 3.7% of the clip, well below the threshold."
    result = validate_note(note, FINDINGS)
    assert not result.ok
    assert any("3.7" in v for v in result.violations)


def test_rejects_a_rule_that_did_not_fire():
    note = "This breaches R99 and should be blocked."
    result = validate_note(note, FINDINGS)
    assert not result.ok
    assert any("R99" in v for v in result.violations)


def test_rejects_an_invented_quotation():
    """A model reciting handbook text from memory is fabricating a record."""
    note = 'The handbook states "the warning must be legible at all times and in all placements".'
    result = validate_note(note, FINDINGS)
    assert not result.ok
    assert any("quotes" in v for v in result.violations)


def test_rejects_a_citation_outside_the_rulebook():
    note = "This engages SYSC 4.1.1R and must be escalated."
    result = validate_note(note, FINDINGS)
    assert not result.ok
    assert any("SYSC" in v for v in result.violations)


def test_rejects_a_plausible_but_wrong_threshold():
    """95% sounds right for "on screen throughout". The rulebook says 98%."""
    note = "The warning falls below the 95% visibility requirement."
    result = validate_note(note, FINDINGS)
    assert not result.ok


def test_reports_every_violation_not_just_the_first():
    note = "R99 found the warning visible 3.7% of the time, breaching SYSC 4.1.1R."
    result = validate_note(note, FINDINGS)
    assert len(result.violations) >= 3


# --------------------------------------------------------------------------
# unit conversion must not cause false rejections
# --------------------------------------------------------------------------


def test_accepts_human_units_for_values_stored_in_fixed_units():
    """800 basis points is correctly written "8.0%" — that must not be rejected.

    A validator that rejects correct notes is as useless as one that accepts
    wrong ones: it would push every note to the template and the model would
    stop earning its place.
    """
    note = "Measured visibility was 8.0% against a 98% threshold."
    assert validate_note(note, FINDINGS).ok


def test_accepts_contrast_written_as_a_ratio():
    note = "Warning contrast measured 3.10:1 against the 4.5:1 threshold."
    assert validate_note(note, FINDINGS).ok


# --------------------------------------------------------------------------
# write_note orchestration
# --------------------------------------------------------------------------


def test_write_note_without_a_model_uses_the_template():
    result = write_note(FINDINGS)
    assert result.source == "template"
    assert result.is_template
    assert "Not legal advice" in result.text


def test_write_note_accepts_a_clean_model_answer():
    def model(prompt: str) -> str:
        return "The warning is on screen for 8.0% of frames, below the 98% threshold. R4 failed."

    result = write_note(FINDINGS, model_fn=model)
    assert result.source == "model"
    assert result.attempts == 1


def test_write_note_retries_once_then_falls_back():
    calls = {"n": 0}

    def model(prompt: str) -> str:
        calls["n"] += 1
        return "The warning showed for 3.7% of frames."  # never valid

    result = write_note(FINDINGS, model_fn=model)
    assert calls["n"] == 2, "must retry exactly once before giving up"
    assert result.source == "template"
    assert result.validation.violations


def test_write_note_accepts_a_corrected_retry():
    calls = {"n": 0}

    def model(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "Visible only 3.7% of the time."
        return "Visible for 8.0% of frames against a 98% threshold."

    result = write_note(FINDINGS, model_fn=model)
    assert result.source == "model_after_retry"
    assert result.attempts == 2


def test_retry_prompt_tells_the_model_what_was_wrong():
    calls: list[str] = []

    def model(prompt: str) -> str:
        calls.append(prompt)
        return "Visible only 3.7% of the time."

    write_note(FINDINGS, model_fn=model)
    assert "rejected" in calls[1]
    assert "3.7" in calls[1]


def test_a_model_exception_falls_back_rather_than_failing_the_check():
    """A model outage must degrade the note, never break the compliance run."""

    def model(prompt: str) -> str:
        raise RuntimeError("503 from the API")

    result = write_note(FINDINGS, model_fn=model)
    assert result.source == "template"
    assert "Not legal advice" in result.text


# --------------------------------------------------------------------------
# the prompt itself
# --------------------------------------------------------------------------


def test_prompt_contains_only_failed_and_inconclusive_findings():
    prompt = build_prompt(FINDINGS)
    assert "R4" in prompt
    passed = [f.rule_id for f in FINDINGS if f.status == "pass"]
    for rule_id in passed:
        assert f"- {rule_id} [pass]" not in prompt


def test_prompt_states_the_hard_constraints():
    prompt = build_prompt(FINDINGS)
    assert "ONLY" in prompt
    assert "Do not introduce any number" in prompt


# --------------------------------------------------------------------------
# evidence bundle
# --------------------------------------------------------------------------


def test_evidence_bundle_collects_rule_ids_and_citations():
    bundle = evidence_bundle(FINDINGS)
    assert "R4" in bundle["rule_ids"]
    assert any("FG24/1" in c for c in bundle["citations"])


def test_template_note_names_inconclusive_rules_and_refuses_to_call_them_passes():
    note = template_note(FINDINGS)
    assert "inconclusive" in note
    assert "not treated as passes" in note


def test_template_note_carries_caveats_from_findings():
    note = template_note(FINDINGS)
    assert "engineering proxy" in note or "Caveat:" in note


@pytest.mark.parametrize(
    "fabrication",
    [
        "The APR appears for 0.4 seconds.",
        "Contrast was 2.1:1.",
        "This breaches COBS 2.1.1R.",
        "Seventeen other ads share this asset.",  # words, not digits
    ],
)
def test_assorted_fabrications_are_caught_or_harmless(fabrication):
    result = validate_note(fabrication, FINDINGS)
    # Numeric and citation fabrications must be caught. Spelled-out numbers carry
    # no measurement claim the validator can check, so they are allowed through —
    # a limitation worth stating rather than pretending away.
    if any(ch.isdigit() for ch in fabrication):
        assert not result.ok, f"missed fabrication: {fabrication}"
