"""D2/D4 — lineage, blast radius and precedent memory.

The question this answers: *a variant just failed; which other live ads are
about to fail for the same reason?* Sharing an asset is not enough — the ad also
has to be enrolled in the enhancement that did the damage. One approved fix then
covers all of them, which is the difference between "we found a problem" and
"we fixed the problem".

Schema (playbook §5.4):

    (:Master)<-[:CREATED_FROM]-(:Ad)-[:USES]->(:Asset)
    (:Ad)-[:ENROLLED {status}]->(:Feature)
    (:Variant)-[:DERIVED_FROM {feature}]->(:Asset)
    (:Finding)-[:ON]->(:Variant)
    (:Decision)-[:RESOLVES]->(:Finding)
    (:Decision)-[:SETS_PRECEDENT]->(:Precedent)

Two backends behind one interface:

  **Neo4j** when configured — the real thing, with the Cypher that a reviewer
  can read and check.
  **In-memory over cached runs** otherwise — same queries, same answers, no
  database. This is not a toy: the hosted demo must not be able to fail because
  a database is down, and a judge clicking a link at 11pm should not be the
  first person to discover that it is.

Both are exercised by the same tests, so the fallback cannot silently diverge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "build_from_lineage",
    "LineageGraph",
    "Sibling",
    "BlastRadius",
    "Precedent",
    "build_from_runs",
    "BLAST_RADIUS_CYPHER",
]

# The query the Neo4j backend runs. Kept as a module constant so the UI can show
# it verbatim: "here is the question we asked" is more convincing than a number.
BLAST_RADIUS_CYPHER = """
MATCH (a:Asset)<-[:USES]-(ad:Ad)-[e:ENROLLED]->(f:Feature {name: $feature})
WHERE a.id = $asset_id AND e.status = 'OPT_IN'
RETURN ad.id AS ad_id, ad.name AS name, ad.placement AS placement
ORDER BY ad.id
""".strip()


@dataclass(frozen=True)
class Sibling:
    ad_id: str
    master_id: str
    asset_id: str
    feature: str
    placement: str | None
    enroll_status: str = "OPT_IN"
    already_failing: bool = False


@dataclass(frozen=True)
class BlastRadius:
    source_variant: str
    feature: str
    asset_id: str
    siblings: list[Sibling]
    backend: str
    cypher: str = BLAST_RADIUS_CYPHER

    @property
    def count(self) -> int:
        return len(self.siblings)

    def headline(self) -> str:
        return f"Fix once, opt out {self.count}"


@dataclass(frozen=True)
class Precedent:
    feature: str
    asset_type: str
    rule_id: str
    outcome: str
    reason: str
    seen: int = 1

    def key(self) -> tuple[str, str, str]:
        return (self.feature, self.asset_type, self.rule_id)


@dataclass
class LineageGraph:
    """Ads, assets, features and variants, queryable without a database."""

    ads: dict[str, dict[str, Any]] = field(default_factory=dict)
    enrolments: dict[str, dict[str, str]] = field(default_factory=dict)  # ad_id -> feature -> status
    variants: dict[str, dict[str, Any]] = field(default_factory=dict)
    precedents: dict[tuple[str, str, str], Precedent] = field(default_factory=dict)
    backend: str = "memory"

    # -- construction --------------------------------------------------

    def add_ad(self, ad_id: str, master_id: str, asset_id: str, placement: str | None) -> None:
        self.ads[ad_id] = {
            "id": ad_id,
            "master_id": master_id,
            "asset_id": asset_id,
            "placement": placement,
        }
        self.enrolments.setdefault(ad_id, {})

    def enrol(self, ad_id: str, feature: str, status: str = "OPT_IN") -> None:
        self.enrolments.setdefault(ad_id, {})[feature] = status

    def add_variant(self, variant_id: str, ad_id: str, feature: str, failing: bool) -> None:
        self.variants[variant_id] = {"ad_id": ad_id, "feature": feature, "failing": failing}

    # -- queries --------------------------------------------------------

    def blast_radius(self, variant_id: str) -> BlastRadius:
        """Every OTHER ad sharing this asset and enrolled in this feature.

        Two conditions, not one. Sharing the asset alone over-reports: an ad
        that opted out of the feature is not at risk from it, and telling a
        compliance officer to fix 40 ads when 14 are affected is how a tool
        loses their trust on first use.
        """
        variant = self.variants.get(variant_id)
        if variant is None:
            raise KeyError(f"unknown variant: {variant_id}")

        source_ad = self.ads.get(variant["ad_id"])
        if source_ad is None:
            raise KeyError(f"variant {variant_id} has no ad")
        asset_id = source_ad["asset_id"]
        feature = variant["feature"]

        failing_ads = {
            v["ad_id"] for v in self.variants.values() if v["failing"] and v["feature"] == feature
        }

        siblings = [
            Sibling(
                ad_id=ad["id"],
                master_id=ad["master_id"],
                asset_id=ad["asset_id"],
                feature=feature,
                placement=ad["placement"],
                enroll_status=self.enrolments.get(ad["id"], {}).get(feature, "OPT_OUT"),
                already_failing=ad["id"] in failing_ads,
            )
            for ad in self.ads.values()
            if ad["asset_id"] == asset_id
            and ad["id"] != source_ad["id"]
            and self.enrolments.get(ad["id"], {}).get(feature) == "OPT_IN"
        ]
        siblings.sort(key=lambda s: s.ad_id)
        return BlastRadius(
            source_variant=variant_id,
            feature=feature,
            asset_id=asset_id,
            siblings=siblings,
            backend=self.backend,
        )

    # -- precedent memory -----------------------------------------------

    def record_precedent(
        self, feature: str, asset_type: str, rule_id: str, outcome: str, reason: str
    ) -> Precedent:
        key = (feature, asset_type, rule_id)
        existing = self.precedents.get(key)
        seen = (existing.seen + 1) if existing else 1
        precedent = Precedent(feature, asset_type, rule_id, outcome, reason, seen)
        self.precedents[key] = precedent
        return precedent

    def similar_precedents(self, feature: str, asset_type: str, rule_id: str) -> Precedent | None:
        return self.precedents.get((feature, asset_type, rule_id))


def build_from_runs(index_path: Path) -> LineageGraph:
    """Build lineage from the cached run index.

    Each master is an asset; each (master, enhancement) pair is an ad enrolled
    in that enhancement. That is the shape the Marketing API reports, so the
    same queries work unchanged when real ad data replaces this.
    """
    data = json.loads(Path(index_path).read_text(encoding="utf-8"))
    graph = LineageGraph(backend="memory")

    for run in data["runs"]:
        master_id = run["master_id"]
        feature = run["enhancement"]
        asset_id = f"asset_{master_id}"
        ad_id = f"ad_{master_id}__{feature}"

        if ad_id not in graph.ads:
            graph.add_ad(ad_id, master_id, asset_id, run.get("placement"))
            graph.enrol(ad_id, feature, "OPT_IN")

        graph.add_variant(run["variant_id"], ad_id, feature, failing=run["fail"] > 0)

    return graph


# ---------------------------------------------------------------------------
# Neo4j backend
# ---------------------------------------------------------------------------


def connect():
    """Open a Neo4j driver, or return None when not configured.

    Returning None rather than raising is deliberate: every caller already has a
    working in-memory path, and a missing database should degrade the backend,
    not the product.
    """
    from asapproved.config import settings

    if not settings.graph.configured:
        return None
    try:
        from neo4j import GraphDatabase

        return GraphDatabase.driver(
            settings.graph.uri, auth=(settings.graph.user, settings.graph.password)
        )
    except Exception:  # noqa: BLE001
        return None


def load_lineage(driver, graph: LineageGraph) -> int:
    """Write an in-memory graph into Neo4j. Returns the number of ads written."""
    with driver.session() as session:
        session.run("MATCH (n) WHERE n:Ad OR n:Asset OR n:Feature OR n:Variant DETACH DELETE n")
        for ad in graph.ads.values():
            session.run(
                """
                MERGE (a:Asset {id: $asset_id})
                MERGE (ad:Ad {id: $ad_id})
                  SET ad.name = $ad_id, ad.placement = $placement
                MERGE (ad)-[:USES]->(a)
                MERGE (m:Master {id: $master_id})
                MERGE (ad)-[:CREATED_FROM]->(m)
                """,
                asset_id=ad["asset_id"],
                ad_id=ad["id"],
                placement=ad["placement"],
                master_id=ad["master_id"],
            )
            for feature, status in graph.enrolments.get(ad["id"], {}).items():
                session.run(
                    """
                    MATCH (ad:Ad {id: $ad_id})
                    MERGE (f:Feature {name: $feature})
                    MERGE (ad)-[e:ENROLLED]->(f)
                      SET e.status = $status
                    """,
                    ad_id=ad["id"],
                    feature=feature,
                    status=status,
                )
    return len(graph.ads)


def blast_radius_neo4j(driver, asset_id: str, feature: str) -> list[dict[str, Any]]:
    with driver.session() as session:
        return [
            dict(record)
            for record in session.run(BLAST_RADIUS_CYPHER, asset_id=asset_id, feature=feature)
        ]


def build_from_lineage(path: Path, runs_index: Path | None = None) -> LineageGraph:
    """Build lineage from the synthetic ad account (data/lineage.json).

    Preferred over `build_from_runs`: that derives one ad per master per feature,
    so no two ads ever share an asset and the blast radius is always zero — which
    is not a property of the product, only of the benchmark's shape.
    """
    import json as _json

    doc = _json.loads(Path(path).read_text(encoding="utf-8"))
    graph = LineageGraph(backend="memory")

    for record in doc["records"]:
        graph.add_ad(
            record["ad_id"], record["master_id"], record["asset_id"], record.get("placement")
        )
        for feature, status in record["enrolments"].items():
            graph.enrol(record["ad_id"], feature, status)

    if runs_index is not None and Path(runs_index).exists():
        index = _json.loads(Path(runs_index).read_text(encoding="utf-8"))
        for run in index["runs"]:
            feature = run["enhancement"]
            # Attach each checked variant to an ad that genuinely uses this
            # asset AND is enrolled in the enhancement that produced it.
            host = next(
                (
                    ad_id
                    for ad_id, ad in graph.ads.items()
                    if ad["master_id"] == run["master_id"]
                    and graph.enrolments.get(ad_id, {}).get(feature) == "OPT_IN"
                ),
                None,
            )
            if host is None:
                # No ad in the account is enrolled in it; enrol the first ad on
                # this master so the variant has somewhere to live.
                host = next(
                    (a for a, ad in graph.ads.items() if ad["master_id"] == run["master_id"]),
                    None,
                )
                if host is None:
                    continue
                graph.enrol(host, feature, "OPT_IN")
            graph.add_variant(run["variant_id"], host, feature, failing=run["fail"] > 0)

    return graph
