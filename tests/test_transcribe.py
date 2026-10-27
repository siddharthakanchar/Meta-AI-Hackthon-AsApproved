"""C7/R9 — spoken parity, at the granularity the API actually provides."""

from __future__ import annotations

from asapproved.models.transcribe import (
    Transcript,
    Turn,
    parse_transcript,
    spoken_check,
)


def _t(*texts: str) -> Transcript:
    return Transcript(
        turns=[Turn(i, "A", text, i * 1000, (i + 1) * 1000) for i, text in enumerate(texts)]
    )


def test_no_transcript_returns_none_not_false():
    """The distinction R9 depends on.

    False means "we listened and the APR was not spoken" — a finding against the
    advertiser. None means "we could not listen". Collapsing them would turn a
    missing capability of ours into a breach of theirs.
    """
    assert spoken_check(Transcript(turns=[], available=False), ["24.9% APR"]) is None
    assert spoken_check(_t("nothing relevant"), ["24.9% APR"]).spoken is False


def test_finds_a_literal_phrase():
    result = spoken_check(_t("Zero percent for twelve months"), ["zero percent for twelve months"])
    assert result.spoken and result.turn_index == 0


def test_finds_a_spoken_rate_written_as_digits():
    """ "24.9%" is said "twenty four point nine percent" — a substring match misses it."""
    transcript = _t(
        "Move your balance today.",
        "Representative 24 point 9 percent APR variable.",
    )
    result = spoken_check(transcript, ["24.9% APR"])
    assert result.spoken
    assert result.turn_index == 1


def test_reports_which_phrase_matched_so_a_reviewer_can_verify():
    result = spoken_check(_t("representative 9 point 9 percent apr"), ["9.9% APR"])
    assert result.spoken
    assert result.matched_phrase


def test_the_r9_case_trigger_spoken_apr_not():
    transcript = _t(
        "Pay zero percent for twelve months with Northfield Card.",
        "Apply in minutes. Credit subject to status.",
    )
    trigger = spoken_check(transcript, ["zero percent for twelve months"])
    apr = spoken_check(transcript, ["24.9% APR", "24 point 9 percent"])
    assert trigger.spoken is True
    assert apr.spoken is False


def test_parse_transcript_reads_turn_level_timings():
    payload = {
        "turns": [
            {"speaker": "A", "text": "hello", "startMs": 0, "endMs": 900},
            {"speaker": "B", "text": "world", "startMs": 900, "endMs": 1800},
        ]
    }
    transcript = parse_transcript(payload)
    assert [t.speaker for t in transcript.turns] == ["A", "B"]
    assert transcript.turns[1].start_ms == 900
    assert transcript.text() == "hello world"


def test_parse_transcript_handles_an_empty_payload():
    transcript = parse_transcript({})
    assert transcript.available and transcript.turns == []
