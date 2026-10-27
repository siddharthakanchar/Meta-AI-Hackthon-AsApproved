"""The region-IoU comparison: the metric itself, and the published result.

IoU is the whole claim here, so it is pinned against hand-computed cases rather
than against whatever the implementation currently returns. The published JSON
is then checked for internal consistency, so a stale `eval/sam_region_delta.json`
cannot drift away from the rows it summarises.
"""

from __future__ import annotations

import json

import pytest

from asapproved.config import REPO_ROOT
from scripts.sam_region_delta import CONCEPTS, ERRORS, EXCLUDED, OUT, iou

# --------------------------------------------------------------------------
# the metric
# --------------------------------------------------------------------------


def test_identical_boxes_score_one():
    assert iou((10, 20, 30, 40), (10, 20, 30, 40)) == 1.0


def test_disjoint_boxes_score_zero():
    assert iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0


def test_boxes_touching_at_an_edge_do_not_overlap():
    assert iou((0, 0, 10, 10), (10, 0, 10, 10)) == 0.0


def test_half_overlap_is_computed_not_guessed():
    # Two 10x10 boxes offset by 5 in x: intersection 5x10=50, union 200-50=150.
    assert iou((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(50 / 150)


def test_a_contained_box_scores_the_area_ratio():
    # 5x5 inside 10x10: intersection 25, union 100.
    assert iou((0, 0, 10, 10), (2, 2, 5, 5)) == pytest.approx(25 / 100)


def test_a_missing_detection_scores_zero_rather_than_raising():
    """A detector that finds nothing must score 0, not crash the comparison."""
    assert iou(None, (0, 0, 10, 10)) == 0.0
    assert iou((0, 0, 10, 10), None) == 0.0
    assert iou(None, None) == 0.0


def test_a_zero_area_box_does_not_divide_by_zero():
    assert iou((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0


def test_iou_is_symmetric():
    a, b = (3, 7, 11, 13), (5, 9, 17, 4)
    assert iou(a, b) == iou(b, a)


# --------------------------------------------------------------------------
# the published result
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def published() -> dict:
    if not OUT.exists():
        pytest.skip(f"{OUT.name} not generated yet")
    return json.loads(OUT.read_text(encoding="utf-8"))


def test_every_error_variant_is_either_scored_or_explicitly_excluded(published):
    """Quietly dropping an awkward case is how a flattering mean gets published."""
    scored = {r["variant_id"] for r in published["rows"]}
    excluded = {e["variant_id"] for e in published["excluded"]}

    assert scored == {v for _, _, v in ERRORS}
    assert excluded == {EXCLUDED["variant_id"]}
    assert scored.isdisjoint(excluded)
    for entry in published["excluded"]:
        assert entry["reason"].strip(), "an exclusion must carry its reason"


def test_the_summary_agrees_with_the_rows_it_summarises(published):
    rows, summary = published["rows"], published["summary"]
    n = len(rows)

    assert summary["variants"] == n
    assert summary["mean_template_iou"] == pytest.approx(
        sum(r["template_iou"] for r in rows) / n, abs=5e-5
    )
    assert summary["mean_sam_iou"] == pytest.approx(sum(r["sam_iou"] for r in rows) / n, abs=5e-5)
    assert summary["mean_delta"] == pytest.approx(
        summary["mean_sam_iou"] - summary["mean_template_iou"], abs=1e-4
    )
    assert summary["template_found"] == sum(1 for r in rows if r["template_box"])
    assert summary["sam_found"] == sum(1 for r in rows if r["sam_box"])


def test_each_rows_iou_matches_its_own_boxes(published):
    """The figures must be derivable from the boxes beside them."""
    for row in published["rows"]:
        truth = tuple(row["truth_box"]) if row["truth_box"] else None
        tmpl = tuple(row["template_box"]) if row["template_box"] else None
        sam = tuple(row["sam_box"]) if row["sam_box"] else None

        assert row["template_iou"] == pytest.approx(iou(tmpl, truth), abs=5e-5)
        assert row["sam_iou"] == pytest.approx(iou(sam, truth), abs=5e-5)
        assert row["delta"] == pytest.approx(row["sam_iou"] - row["template_iou"], abs=1e-4)


def test_no_mask_level_score_is_claimed(published):
    """SAM returns masks this repo cannot decode; the metric is box IoU only."""
    assert published["summary"]["metric"] == "box_iou"
    assert published["summary"]["masks_used"] is False
    assert all(row["mask_available"] is False for row in published["rows"])


def test_the_concept_sensitivity_is_recorded_not_hidden(published):
    """Reporting only the winning phrase would hide that most phrases find nothing."""
    assert published["summary"]["concepts"] == CONCEPTS
    for row in published["rows"]:
        assert set(row["per_concept"]) == set(CONCEPTS)
        found = sum(1 for v in row["per_concept"].values() if v["box"])
        assert row["concepts_that_found_it"] == found
        if row["sam_box"]:
            assert row["sam_concept"] in CONCEPTS
            assert row["per_concept"][row["sam_concept"]]["box"] == row["sam_box"]


def test_the_recorded_responses_are_committed(published):
    """Without them the result does not reproduce from a clean clone.

    data/cache/ was gitignored with the regenerable assets, but a recorded model
    response cannot be regenerated without a key.
    """
    import subprocess

    cached = subprocess.run(
        ["git", "ls-files", "data/cache"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert cached, "no recorded responses are tracked; the SAM result cannot be replayed"


def test_no_recorded_response_carries_a_credential():
    """Committing the cache puts recorded traffic in a public repo.

    gitleaks flags these files for a field named `"key"` holding 64 high-entropy
    characters; that field was the cache key, which is also the filename, and it
    has been removed. This checks the thing that actually matters rather than
    relying on a scanner's heuristic.
    """
    from asapproved.config import settings

    secrets = [
        v
        for v in (
            settings.models.api_key,
            settings.marketing.access_token,
            settings.marketing.app_secret,
        )
        if v
    ]

    for path in (REPO_ROOT / "data" / "cache").rglob("*.json"):
        body = path.read_text(encoding="utf-8")
        assert "key" not in json.loads(body), f"{path.name} still carries a 'key' field"
        for secret in secrets:
            assert secret not in body, f"{path.name} contains a configured credential"
