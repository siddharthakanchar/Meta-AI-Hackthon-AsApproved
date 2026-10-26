"""D2/D3 — blast radius, and the Act/Prove loop.

The behaviour under test is mostly about restraint: not over-reporting siblings,
not acting by default, and not calling a fix proven when it was never observed.
"""

from __future__ import annotations

import pytest

from asapproved.act import apply_opt_out, plan_opt_out, prove
from asapproved.graph import LineageGraph


@pytest.fixture()
def graph() -> LineageGraph:
    g = LineageGraph()
    # Three ads share asset A; two are enrolled in image_animation.
    g.add_ad("ad1", "master_a", "asset_a", "reels")
    g.add_ad("ad2", "master_a", "asset_a", "feed")
    g.add_ad("ad3", "master_a", "asset_a", "stories")
    # A fourth ad uses a different asset but the same feature.
    g.add_ad("ad4", "master_b", "asset_b", "reels")

    g.enrol("ad1", "image_animation", "OPT_IN")
    g.enrol("ad2", "image_animation", "OPT_IN")
    g.enrol("ad3", "image_animation", "OPT_OUT")  # opted out — not at risk
    g.enrol("ad4", "image_animation", "OPT_IN")

    g.add_variant("v1", "ad1", "image_animation", failing=True)
    g.add_variant("v2", "ad2", "image_animation", failing=False)
    return g


# --------------------------------------------------------------------------
# blast radius
# --------------------------------------------------------------------------


def test_blast_radius_needs_both_asset_and_feature(graph):
    """Shared asset alone over-reports; shared feature alone is a different ad.

    Telling a compliance officer to fix 40 ads when 14 are affected is how a
    tool loses their trust the first time they check it by hand.
    """
    result = graph.blast_radius("v1")
    ids = [s.ad_id for s in result.siblings]

    assert "ad2" in ids, "same asset, same feature, opted in — at risk"
    assert "ad3" not in ids, "same asset but OPTED OUT of the feature — not at risk"
    assert "ad4" not in ids, "same feature but a different asset — unaffected"
    assert "ad1" not in ids, "the source ad is not its own sibling"
    assert result.count == 1


def test_blast_radius_headline_is_the_demo_line(graph):
    assert graph.blast_radius("v1").headline() == "Fix once, opt out 1"


def test_blast_radius_exposes_the_query_it_ran(graph):
    """Showing the Cypher is more convincing than showing a number."""
    result = graph.blast_radius("v1")
    assert "ENROLLED" in result.cypher
    assert "OPT_IN" in result.cypher
    assert result.backend == "memory"


def test_blast_radius_marks_siblings_already_failing(graph):
    graph.add_variant("v3", "ad2", "image_animation", failing=True)
    result = graph.blast_radius("v1")
    assert any(s.already_failing for s in result.siblings)


def test_unknown_variant_raises(graph):
    with pytest.raises(KeyError):
        graph.blast_radius("nope")


def test_build_from_runs(tmp_path):
    import json

    index = {
        "runs": [
            {"variant_id": "a1", "master_id": "m1", "enhancement": "image_touchups", "fail": 2, "placement": "feed"},
            {"variant_id": "a2", "master_id": "m1", "enhancement": "image_touchups", "fail": 0, "placement": "feed"},
            {"variant_id": "b1", "master_id": "m2", "enhancement": "image_touchups", "fail": 0, "placement": "reels"},
        ]
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index), encoding="utf-8")

    from asapproved.graph import build_from_runs

    g = build_from_runs(path)
    result = g.blast_radius("a1")
    # m2 shares the feature but not the asset, so it is not in the radius.
    assert [s.master_id for s in result.siblings] == []


# --------------------------------------------------------------------------
# precedent memory
# --------------------------------------------------------------------------


def test_precedents_accumulate(graph):
    for _ in range(3):
        graph.record_precedent(
            "image_touchups", "still", "R1", "accepted", "touch-up on a non-claim area"
        )
    found = graph.similar_precedents("image_touchups", "still", "R1")
    assert found is not None
    assert found.seen == 3
    assert found.outcome == "accepted"


def test_precedents_are_scoped_to_feature_asset_and_rule(graph):
    graph.record_precedent("image_touchups", "still", "R1", "accepted", "x")
    assert graph.similar_precedents("image_animation", "still", "R1") is None
    assert graph.similar_precedents("image_touchups", "video", "R1") is None
    assert graph.similar_precedents("image_touchups", "still", "R6") is None


# --------------------------------------------------------------------------
# Act
# --------------------------------------------------------------------------


def test_plan_is_pure_and_deduplicated():
    plan = plan_opt_out(["ad2", "ad1", "ad1"], "image_animation", reason="R4 failed")
    assert [p.ad_id for p in plan.payloads] == ["ad1", "ad2"]
    assert plan.count == 2


def test_plan_payload_shape():
    plan = plan_opt_out(["ad1"], "image_animation")
    body = plan.payloads[0].body()
    spec = body["degrees_of_freedom_spec"]["creative_features_spec"]
    assert spec["image_animation"]["enroll_status"] == "OPT_OUT"


def test_plan_requires_a_feature():
    with pytest.raises(ValueError, match="feature"):
        plan_opt_out(["ad1"], "")


def test_act_defaults_to_dry_run():
    """Acting on a live ad account must never happen by omission."""
    plan = plan_opt_out(["ad1", "ad2"], "image_animation")
    result = apply_opt_out(plan)
    assert result.dry_run is True
    assert "DRY RUN" in result.label
    assert result.succeeded == ["ad1", "ad2"]


def test_act_without_a_client_stays_a_dry_run_even_if_asked_not_to():
    plan = plan_opt_out(["ad1"], "image_animation")
    result = apply_opt_out(plan, dry_run=False, client=None)
    assert result.dry_run is True


def test_act_reports_per_ad_failures_without_aborting_the_batch():
    class FlakyClient:
        def __init__(self):
            self.calls = []

        def update_ad_creative(self, ad_id, body):
            self.calls.append(ad_id)
            if ad_id == "ad2":
                raise RuntimeError("rate limited")

    client = FlakyClient()
    plan = plan_opt_out(["ad1", "ad2", "ad3"], "image_animation")
    result = apply_opt_out(plan, dry_run=False, client=client)

    assert client.calls == ["ad1", "ad2", "ad3"], "one failure must not stop the rest"
    assert result.succeeded == ["ad1", "ad3"]
    assert "rate limited" in result.failed["ad2"]
    assert result.ok is False


# --------------------------------------------------------------------------
# Prove
# --------------------------------------------------------------------------


def test_prove_without_a_client_never_claims_success():
    """The most important assertion in this file.

    Reporting a fix as proven when nothing was observed would make the whole
    evidence trail worthless.
    """
    results = prove(["ad1", "ad2"], "image_animation")
    assert all(not r.proven for r in results)
    assert all(r.status == "Open – could not verify" for r in results)


def test_prove_requires_both_settings_and_rendering():
    class Client:
        def enroll_status(self, ad_id, feature):
            return "OPT_OUT"

    # Settings confirmed but no re-render: not proven.
    results = prove(["ad1"], "image_animation", client=Client())
    assert results[0].settings_opted_out is True
    assert results[0].preview_matches_master is None
    assert not results[0].proven

    # Both confirmed: proven.
    results = prove(["ad1"], "image_animation", client=Client(), recheck=lambda ad: True)
    assert results[0].proven
    assert results[0].status == "Closed – proven"


def test_prove_fails_closed_when_the_rerender_still_differs():
    class Client:
        def enroll_status(self, ad_id, feature):
            return "OPT_OUT"

    results = prove(["ad1"], "image_animation", client=Client(), recheck=lambda ad: False)
    assert not results[0].proven
    assert results[0].status == "Open – fix not confirmed"


def test_prove_reports_a_settings_read_failure():
    class Client:
        def enroll_status(self, ad_id, feature):
            raise RuntimeError("token expired")

    results = prove(["ad1"], "image_animation", client=Client())
    assert not results[0].proven
    assert "token expired" in results[0].note
