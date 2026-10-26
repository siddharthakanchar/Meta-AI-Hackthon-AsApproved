"""C12 — hash-chained evidence log, including the tamper demo from §11 screen 4."""

from __future__ import annotations

import json

import pytest

from asapproved.evidence import (
    GENESIS_PREV,
    append_record,
    export_json,
    head_hash,
    verify_chain,
)


def _seed(log, n=3):
    for i in range(n):
        append_record(
            log,
            {
                "variant_id": f"northfield_card_01_v{i}",
                "decision": "block" if i == 1 else "accept",
                "rule_ids": ["R4", "R8"] if i == 1 else [],
                "ms_visible": 1200 + i,
            },
        )


def test_empty_and_missing_logs(tmp_path):
    log = tmp_path / "evidence.jsonl"
    assert head_hash(log) == GENESIS_PREV
    result = verify_chain(log)
    assert not result.ok and "no such log" in result.reason


def test_append_and_verify(tmp_path):
    log = tmp_path / "evidence.jsonl"
    _seed(log, 3)

    result = verify_chain(log)
    assert result.ok, result.reason
    assert result.entries == 3
    assert result.head == head_hash(log)
    assert result.first_bad_index is None


def test_first_record_links_to_genesis(tmp_path):
    log = tmp_path / "evidence.jsonl"
    entry = append_record(log, {"decision": "accept"})
    assert entry.index == 0
    assert entry.prev == GENESIS_PREV


def test_tamper_one_byte_is_caught_at_the_right_record(tmp_path):
    """The demo moment: edit one character, verification names record k."""
    log = tmp_path / "evidence.jsonl"
    _seed(log, 4)
    assert verify_chain(log).ok

    lines = log.read_text(encoding="utf-8").splitlines()
    raw = json.loads(lines[1])
    assert raw["record"]["decision"] == "block", "record 1 is the one worth faking"
    raw["record"]["decision"] = "accept"
    lines[1] = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(log)
    assert not result.ok
    assert result.first_bad_index == 1
    assert result.first_bad_line == 2
    assert "has been altered" in result.reason


def test_reordering_records_is_caught(tmp_path):
    """Swapping two intact records preserves every individual hash.

    Only because the hash covers `index` and `prev` does reordering fail — which
    is the reason those fields are inside the digest, not alongside it.
    """
    log = tmp_path / "evidence.jsonl"
    _seed(log, 3)
    lines = log.read_text(encoding="utf-8").splitlines()
    lines[0], lines[1] = lines[1], lines[0]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(log)
    assert not result.ok
    assert "out of order" in result.reason


def test_deleting_a_record_breaks_the_link(tmp_path):
    log = tmp_path / "evidence.jsonl"
    _seed(log, 4)
    lines = log.read_text(encoding="utf-8").splitlines()
    del lines[1]  # remove an inconvenient block decision
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(log)
    assert not result.ok
    assert "out of order" in result.reason or "broken link" in result.reason


def test_truncating_the_log_still_verifies(tmp_path):
    """Honest limitation: dropping records from the END leaves a valid prefix.

    A hash chain cannot detect truncation on its own — that needs an external
    anchor or a signed head. Pinned as a test so the claim in the README stays
    accurate and nobody later asserts more than the mechanism delivers.
    """
    log = tmp_path / "evidence.jsonl"
    _seed(log, 4)
    full_head = head_hash(log)

    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")

    result = verify_chain(log)
    assert result.ok, "truncation is undetectable from the chain alone"
    assert result.entries == 2
    assert result.head != full_head, "but the head hash changes, so an anchored head catches it"


def test_malformed_line_is_reported_not_raised(tmp_path):
    log = tmp_path / "evidence.jsonl"
    _seed(log, 2)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{not json at all\n")

    result = verify_chain(log)
    assert not result.ok
    assert result.first_bad_line == 3
    assert "not valid JSON" in result.reason


def test_refuses_to_append_to_a_damaged_log(tmp_path):
    log = tmp_path / "evidence.jsonl"
    _seed(log, 1)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("garbage\n")

    with pytest.raises(ValueError, match="verify-log"):
        append_record(log, {"decision": "accept"})


def test_floats_rejected_in_records(tmp_path):
    log = tmp_path / "evidence.jsonl"
    with pytest.raises(TypeError, match="float at"):
        append_record(log, {"seconds_visible": 1.2})


def test_export_json_includes_verification_status(tmp_path):
    log = tmp_path / "evidence.jsonl"
    _seed(log, 2)
    out = export_json(log, tmp_path / "pack.json")

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert len(doc["entries"]) == 2
    assert doc["verification"]["ok"] is True
    assert doc["verification"]["head"] == head_hash(log)
    assert "COBS 4.11.1R" in doc["retention_note"]
    assert "not legal advice" in doc["retention_note"]


def test_export_reports_failure_rather_than_hiding_it(tmp_path):
    log = tmp_path / "evidence.jsonl"
    _seed(log, 3)
    lines = log.read_text(encoding="utf-8").splitlines()
    raw = json.loads(lines[1])
    raw["record"]["decision"] = "accept"
    lines[1] = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    doc = json.loads(export_json(log, tmp_path / "pack.json").read_text(encoding="utf-8"))
    assert doc["verification"]["ok"] is False
    assert doc["verification"]["first_bad_index"] == 1
