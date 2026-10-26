"""The review UI reads only precomputed files. These test that contract.

A Streamlit page cannot be unit-tested usefully, but everything that can break
it can: a missing preview, a findings record with a field the renderer does not
expect, an index that disagrees with the per-variant files. Those are the
failures that would surface as a blank panel in front of a judge.
"""

from __future__ import annotations

import json

import pytest

from asapproved.config import settings

RUNS = settings.data_dir / "runs"
pytestmark = pytest.mark.skipif(
    not (RUNS / "index.json").exists(), reason="no precomputed runs; run scripts/precompute.py"
)


@pytest.fixture(scope="module")
def index() -> dict:
    return json.loads((RUNS / "index.json").read_text(encoding="utf-8"))


def test_index_covers_every_run(index):
    assert index["count"] == len(index["runs"])
    assert index["count"] >= 40


def test_every_indexed_run_has_its_record(index):
    for row in index["runs"]:
        assert (RUNS / f"{row['variant_id']}.json").exists(), row["variant_id"]


def test_index_summary_matches_the_record(index):
    """The index is a cache of the records; a stale one silently misreports.

    Caught a real confusion: precompute writes the index LAST, so mid-run the
    index describes the previous build while the per-variant files describe the
    current one. Comparing the two was how a fix looked like it had not worked.
    """
    for row in index["runs"]:
        record = json.loads((RUNS / f"{row['variant_id']}.json").read_text(encoding="utf-8"))
        assert sorted(row["failed_rules"]) == sorted(record["summary"]["failed_rules"]), (
            f"{row['variant_id']}: index disagrees with its record — stale cache"
        )
        assert row["fail"] == record["summary"]["fail"]


def test_every_preview_file_exists(index):
    for row in index["runs"]:
        record = json.loads((RUNS / f"{row['variant_id']}.json").read_text(encoding="utf-8"))
        for kind, name in record["previews"].items():
            assert (RUNS / "previews" / name).exists(), f"{row['variant_id']}/{kind}"


def test_findings_carry_everything_the_renderer_reads(index):
    required = {"rule_id", "status", "severity", "citation", "detail"}
    for row in index["runs"][:12]:
        record = json.loads((RUNS / f"{row['variant_id']}.json").read_text(encoding="utf-8"))
        for finding in record["findings"]:
            assert required <= finding.keys(), finding.get("rule_id")
            assert finding["status"] in {"fail", "pass", "inconclusive", "not_applicable"}


def test_every_record_states_its_provenance(index):
    """The UI promises to say how each region was located. It must be able to."""
    for row in index["runs"][:12]:
        record = json.loads((RUNS / f"{row['variant_id']}.json").read_text(encoding="utf-8"))
        assert record["region_source"]
        assert record["text_source"] in {"ocr", "none"}
        assert record["variant_sha256"]


def test_every_record_has_a_compliance_note(index):
    for row in index["runs"][:12]:
        record = json.loads((RUNS / f"{row['variant_id']}.json").read_text(encoding="utf-8"))
        assert "Not legal advice" in record["note"]


def test_notes_validate_against_their_own_findings(index):
    """The note the UI displays must pass the validator that produced it."""
    from asapproved.explain import validate_note
    from asapproved.rules.engine import Finding

    for row in index["runs"][:10]:
        record = json.loads((RUNS / f"{row['variant_id']}.json").read_text(encoding="utf-8"))
        findings = [
            Finding(
                rule_id=f["rule_id"],
                rulebook_version=f["rulebook_version"],
                title="",
                citation=f["citation"],
                paraphrase="",
                status=f["status"],
                severity=f["severity"],
                detail=f["detail"],
                measured=f.get("measured"),
                measured_display=f.get("measured_display", ""),
                threshold=f.get("threshold"),
                threshold_display=f.get("threshold_display", ""),
                units=f.get("units", "none"),
                evidence=f.get("evidence") or {},
                sub_results=f.get("sub_results") or {},
                caveats=f.get("caveats") or [],
                benchmark_only=f.get("benchmark_only", False),
            )
            for f in record["findings"]
        ]
        result = validate_note(record["note"], findings)
        assert result.ok, f"{row['variant_id']}: {result.violations}"


def test_a_hero_case_exists_for_the_demo(index):
    """The UI defaults to the APR animation. If it is missing the demo opens blank."""
    hero = [r for r in index["runs"] if "apr_animates" in r["variant_id"]]
    assert hero, "no hero variant in the cached runs"
    assert any(r["fail"] > 0 for r in hero), "the hero case does not fail any rule"
