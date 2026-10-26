"""R11 text normalisation: fold encoding, never fold wording."""

from __future__ import annotations

import pytest

from asapproved.synth.specs import prescribed_text
from asapproved.text_norm import diff_summary, normalise, same_prescribed_text

CRYPTO = prescribed_text("cryptoassets")
NRRS = prescribed_text("non_readily_realisable_securities")


# --- encoding differences must be forgiven --------------------------------


def test_curly_and_straight_apostrophes_are_the_same_warning():
    """The case that made this module exist.

    The handbook sets Don't with U+2019; a design tool may emit U+0027. Flagging
    that as an altered warning would be a false positive on correct creative.
    """
    straight = "Don't invest unless you're prepared to lose all the money you invest."
    curly = "Don’t invest unless you’re prepared to lose all the money you invest."
    assert same_prescribed_text(straight, curly)


def test_whitespace_and_case_are_forgiven():
    reflowed = "  DON'T INVEST   unless you're\nprepared to lose all the money you invest. "
    original = "Don't invest unless you're prepared to lose all the money you invest."
    assert same_prescribed_text(reflowed, original)


def test_nbsp_and_dashes_are_forgiven():
    a = "high risk – capital at risk"
    b = "high risk - capital at risk"
    assert same_prescribed_text(a, b)


def test_bom_is_stripped():
    assert same_prescribed_text("﻿capital at risk", "capital at risk")


def test_prescribed_text_round_trips_through_normalisation():
    for key in (
        "cryptoassets",
        "non_readily_realisable_securities",
        "p2p_agreements",
        "long_term_asset_fund",
    ):
        text = prescribed_text(key)
        assert same_prescribed_text(text, text)
        assert normalise(text)  # non-empty


# --- wording differences must NOT be forgiven ------------------------------


def test_crypto_and_nrrs_stay_distinct_after_normalisation():
    """The whole reason for the per-type table (D-007).

    These two differ only in "should not expect to be" vs "are unlikely to be".
    If normalisation ever collapsed them, R11 would pass an altered crypto
    warning and flag a correct one — the exact failure the four-variant table
    was built to prevent. Pinned here as well as in the rulebook test.
    """
    assert not same_prescribed_text(CRYPTO, NRRS)
    assert normalise(CRYPTO) != normalise(NRRS)


@pytest.mark.parametrize(
    "altered",
    [
        # a translation/rewrite of the opening
        "Do not invest unless you are prepared to lose all the money you invest. "
        "This is a high-risk investment and you should not expect to be protected "
        "if something goes wrong.",
        # softened: "all the money" -> "money"
        "Don't invest unless you're prepared to lose money. This is a high-risk "
        "investment and you should not expect to be protected if something goes wrong.",
        # truncated at the end — the classic "it didn't fit" edit
        "Don't invest unless you're prepared to lose all the money you invest.",
        # a reassuring word inserted
        "Don't invest unless you're prepared to lose all the money you invest. "
        "This is a high-risk investment and you should not usually expect to be "
        "protected if something goes wrong.",
    ],
)
def test_reworded_warnings_are_caught(altered):
    assert not same_prescribed_text(altered, CRYPTO)


def test_removed_full_stop_is_treated_as_wording_not_encoding():
    """Deliberately strict: we only fold typographic VARIANTS, not punctuation."""
    assert not same_prescribed_text(CRYPTO.replace(".", ""), CRYPTO)


# --- the finding has to be readable ----------------------------------------


def test_diff_summary_reports_a_match():
    assert diff_summary(CRYPTO, CRYPTO) == "matches the prescribed wording"


def test_diff_summary_points_at_the_changed_word():
    altered = CRYPTO.replace("all the money you invest", "money you invest")
    summary = diff_summary(altered, CRYPTO)
    assert "diverges at word" in summary


def test_diff_summary_reports_truncation():
    truncated = " ".join(CRYPTO.split()[:10])
    summary = diff_summary(truncated, CRYPTO)
    assert "truncated" in summary
    assert "words missing" in summary
