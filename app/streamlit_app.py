"""AsApproved — the review UI.

Reads precomputed runs from `data/runs/`, so the demo needs no API key, no
network and no luck. Everything on screen carries its source: a measurement, a
rule ID, a citation, or an explicit "could not be measured".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.components.render import (  # noqa: E402
    CSS,
    finding_card_html,
    visibility_bar_html,
)
from asapproved import RULEBOOK_VERSION, __version__  # noqa: E402
from asapproved.act import plan_opt_out, prove  # noqa: E402
from asapproved.config import settings  # noqa: E402

st.set_page_config(page_title="AsApproved", page_icon="🛡️", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

RUNS = settings.data_dir / "runs"
PREVIEWS = RUNS / "previews"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def load_index() -> dict | None:
    path = RUNS / "index.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_run(variant_id: str) -> dict | None:
    path = RUNS / f"{variant_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_resource(show_spinner=False)
def load_graph():
    """Lineage over the synthetic ad account, not over the benchmark runs.

    Deriving it from the runs gave one ad per master per feature, so no two ads
    ever shared an asset and the blast radius was always zero — a property of the
    benchmark's shape, not of the product.
    """
    from asapproved.graph import build_from_lineage

    path = settings.data_dir / "lineage.json"
    if not path.exists():
        return None
    return build_from_lineage(path, RUNS / "index.json")


@st.cache_data(show_spinner=False)
def load_eval() -> dict | None:
    path = REPO_ROOT / "eval" / "results.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_rulebook_meta() -> dict:
    from asapproved.rules.engine import load_rulebook

    book = load_rulebook()
    return {
        "version": book.version,
        "status": book.status,
        "verified": book.verified,
        "rules": [
            {"id": r.id, "title": r.title, "citation": r.citation, "severity": r.severity}
            for r in book.rules
        ],
    }


def _decision_log():
    return settings.evidence_dir / "decisions.jsonl"


def _run_decision(variant_id: str, run: dict, action: str) -> None:
    """Execute a decision end to end against the cached data.

    This is the claim the whole product rests on — "fix every affected ad in one
    click" — so it has to actually run, not be described. Every step below is
    the real code path: the same blast-radius query, the same payload builder,
    the same Prove logic and the same hash chain the CLI uses. The only thing
    held back is the network call, which is a labelled dry run because nobody
    has authorised this demo to touch a live ad account.
    """
    from asapproved.act import apply_opt_out, plan_opt_out, prove
    from asapproved.evidence import append_record, verify_chain

    graph = load_graph()
    siblings: list = []
    feature = run["label"]["enhancement"]
    if graph is not None:
        try:
            radius = graph.blast_radius(variant_id)
            siblings = radius.siblings
            feature = radius.feature
        except KeyError:
            siblings = []

    st.divider()
    if action == "block":
        st.markdown(f"### Blocked — fix once, opt out {len(siblings)}")
    else:
        st.markdown(f"### Recorded as *{action}*")

    if action == "block" and siblings:
        st.markdown("**1 · Blast radius** — ads sharing this asset and enrolled in this feature")
        st.dataframe(
            pd.DataFrame(
                [
                    {"ad": s.ad_id, "placement": s.placement, "enrolment": s.enroll_status}
                    for s in siblings
                ]
            ),
            use_container_width=True,
            height=180,
        )

        plan = plan_opt_out(
            [s.ad_id for s in siblings], feature, reason=f"blocked: {variant_id}"
        )
        result = apply_opt_out(plan)  # dry run by default
        st.markdown(f"**2 · Act** — {result.label}")
        st.code(json.dumps(plan.as_requests()[:2], indent=2), language="json")
        if plan.count > 2:
            st.caption(f"…and {plan.count - 2} more identical in shape.")

        st.markdown("**3 · Prove**")
        proof = prove([s.ad_id for s in siblings], feature)
        st.dataframe(
            pd.DataFrame([{"ad": p.ad_id, "status": p.status} for p in proof]),
            use_container_width=True,
            height=160,
        )
        st.caption(
            "Every row reads *could not verify*, not *proven*. Without Marketing API access "
            "nothing was observed, and reporting a fix as proven that we did not watch land "
            "would make the entire evidence trail worthless."
        )

    st.markdown("**4 · Evidence**")
    entry = append_record(
        _decision_log(),
        {
            "variant_id": variant_id,
            "master_id": run["master_id"],
            "decision": action,
            "rule_ids": run["summary"]["failed_rules"],
            "rulebook_version": "uk_v1",
            "variant_sha256": run["variant_sha256"],
            "feature": feature,
            "siblings_opted_out": len(siblings) if action == "block" else 0,
            "dry_run": True,
            "approver": "demo@asapproved.test",
        },
    )
    chain = verify_chain(_decision_log())
    st.success(
        f"record {entry.index} appended · chain {'INTACT' if chain.ok else 'BROKEN'} "
        f"over {chain.entries} records"
    )
    st.code(entry.to_json(), language="json")
    st.caption(
        "The digest covers the record, its index and the previous record's hash — so editing, "
        "reordering or deleting any record breaks verification from that point on. "
        "Check it on the Evidence screen."
    )


index = load_index()


# ---------------------------------------------------------------------------
# chrome
# ---------------------------------------------------------------------------

# Variant review first: the demo opens on the hero case, not on two dataframes.
SCREENS = [
    "Variant review",
    "Overview",
    "Blast radius",
    "Evidence",
    "Benchmark",
    "Rulebook",
]

with st.sidebar:
    st.markdown("### 🛡️ AsApproved")
    st.caption("Turn on Advantage+ without betting your licence.")
    screen = st.radio("Screen", SCREENS, label_visibility="collapsed")
    st.divider()
    st.caption(f"v{__version__} · rulebook `{RULEBOOK_VERSION}`")
    st.caption(f"mode `{settings.mode}` · cached runs, no API calls")
    if index:
        st.caption(f"{index['count']} variants checked")
        st.caption(f"labels `{(index.get('labels_sha256') or '')[:12]}…`")

if index is None:
    st.title("AsApproved")
    st.error(
        "No precomputed runs found. Build the dataset and cache the checks:\n\n"
        "```\npython scripts/make_masters.py\n"
        "python scripts/make_variants.py\n"
        "python scripts/precompute.py\n```"
    )
    st.stop()

RUN_ROWS = index["runs"]


def _simulated_banner() -> None:
    st.markdown(
        '<span class="aa-sim">simulated</span> '
        '<span class="aa-muted">All creative here is synthetic: three fictional firms, '
        "no real brands, no real people. Findings flag items for compliance review against "
        "paraphrased regulation — not legal advice.</span>",
        unsafe_allow_html=True,
    )


def _metric(col, value: str, label: str, css: str = "") -> None:
    col.markdown(
        f'<div class="aa-metric {css}">{value}</div>'
        f'<div class="aa-metric-sub">{label}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

if screen == "Overview":
    st.title("Overview")
    _simulated_banner()
    st.write("")

    df = pd.DataFrame(RUN_ROWS)
    blocking = int(df["blocking"].sum())
    flagged = int((df["fail"] > 0).sum())
    benign_flagged = int(((df["fail"] > 0) & df["benign"]).sum())
    benign_total = int(df["benign"].sum())

    c1, c2, c3, c4 = st.columns(4)
    _metric(c1, str(len(df)), "variants checked")
    _metric(c2, str(flagged), "with at least one failing rule", "aa-fail")
    _metric(c3, str(blocking), "blocking", "aa-fail")
    _metric(
        c4,
        f"{benign_flagged}/{benign_total}",
        "benign variants wrongly flagged",
        "aa-ok" if benign_flagged == 0 else "aa-warn",
    )

    st.write("")
    st.markdown("#### By Meta enhancement")
    st.caption(
        "Which Advantage+ feature produced each variant. This is the grouping the "
        "blast-radius query uses: one approved fix covers every ad sharing an asset and a "
        "feature."
    )
    by_feature = (
        df.groupby("enhancement")
        .agg(variants=("variant_id", "count"), failing=("fail", lambda s: int((s > 0).sum())))
        .sort_values("variants", ascending=False)
    )
    st.dataframe(by_feature, use_container_width=True)

    st.markdown("#### All checks")
    view = df[
        ["variant_id", "benign", "transform", "enhancement", "kind", "fail", "inconclusive", "seconds"]
    ].rename(columns={"fail": "failing rules", "seconds": "s"})
    st.dataframe(view, use_container_width=True, height=420)


# ---------------------------------------------------------------------------
# Variant review — the hero screen
# ---------------------------------------------------------------------------

elif screen == "Variant review":
    st.title("Variant review")
    _simulated_banner()

    hero_candidates = [r["variant_id"] for r in RUN_ROWS if "apr_animates" in r["variant_id"]]
    ids = [r["variant_id"] for r in RUN_ROWS]
    default = ids.index(hero_candidates[0]) if hero_candidates else 0

    variant_id = st.selectbox("Variant", ids, index=default)
    run = load_run(variant_id)
    if run is None:
        st.error("No cached run for this variant.")
        st.stop()

    summary = run["summary"]
    label = run["label"]
    master = run["master"]

    st.write("")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    _metric(c1, str(summary["fail"]), "rules failed", "aa-fail" if summary["fail"] else "aa-ok")
    _metric(
        c2,
        str(summary["inconclusive"]),
        "could not be assessed",
        "aa-warn" if summary["inconclusive"] else "",
    )
    _metric(c3, master["placement"] or "—", "placement")
    c4.markdown(
        f'<div class="aa-muted">Meta enhancement</div>'
        f'<div style="font-size:1.1rem;font-weight:600">{label["enhancement"]}</div>'
        f'<div class="aa-muted">{label["description"]}</div>',
        unsafe_allow_html=True,
    )

    # --- the hero number -------------------------------------------------
    visibility = run.get("visibility") or {}
    fps = run.get("sample_fps") or 0
    apr_key = "apr" if "apr" in visibility else "risk_note"
    if fps and visibility:
        st.write("")
        for key in ("warning", apr_key):
            flags = visibility.get(key)
            if flags and not all(flags):
                st.markdown(visibility_bar_html(flags, fps, key.upper()), unsafe_allow_html=True)
                st.caption(
                    "Green = on screen, red = not. A preview shows frame zero only; this is "
                    "what was delivered."
                )
                break

    st.write("")
    left, right = st.columns([3, 2])

    with left:
        tabs = st.tabs(["Master vs variant", "Change heat map", "Regions + overlay zone"])
        prev = run.get("previews", {})
        with tabs[0]:
            a, b = st.columns(2)
            if prev.get("master"):
                a.image(str(PREVIEWS / prev["master"]), caption="Approved master", width="stretch")
            if prev.get("variant"):
                b.image(str(PREVIEWS / prev["variant"]), caption="Delivered variant", width="stretch")
        with tabs[1]:
            if prev.get("heat"):
                st.image(
                    str(PREVIEWS / prev["heat"]),
                    caption="SSIM divergence — brighter means structurally changed",
                    width="stretch",
                )
            st.caption(
                "SSIM rather than absolute pixel difference: a brightness shift moves every "
                "pixel value while changing no content."
            )
        with tabs[2]:
            if prev.get("annotated"):
                st.image(
                    str(PREVIEWS / prev["annotated"]),
                    caption="Tracked regions, with the placement's reserved UI zone shaded",
                    width="stretch",
                )
            st.caption(
                "The shaded band is where the platform's own chrome sits. FG24/1 para 1.5 says "
                "a warning must not be obscured by a design feature of the platform."
            )

    with right:
        st.markdown("#### Findings")
        order = {"fail": 0, "inconclusive": 1, "pass": 2, "not_applicable": 3}
        for f in sorted(run["findings"], key=lambda x: (order.get(x["status"], 9), x["rule_id"])):
            if f["status"] in ("fail", "inconclusive"):
                st.markdown(finding_card_html(f), unsafe_allow_html=True)

        with st.expander(f"Passed and not applicable ({summary['pass'] + summary['not_applicable']})"):
            for f in run["findings"]:
                if f["status"] in ("pass", "not_applicable"):
                    st.markdown(finding_card_html(f), unsafe_allow_html=True)

    st.write("")
    st.markdown("#### Compliance note")
    st.caption(
        "Generated from the findings and then validated: any number, rule ID or quotation "
        "not present in the evidence is rejected and the note falls back to a deterministic "
        "template. Rules decide; the model only explains."
    )
    st.code(run.get("note", ""), language=None)

    st.markdown("#### Decision")
    st.caption(
        "A decision runs the whole loop: blast radius over the ad account, the opt-out payloads "
        "that would be sent, the Prove step, and an append to the hash-chained evidence log."
    )
    d1, d2, d3 = st.columns(3)
    blocked = d1.button("Block", type="primary", use_container_width=True)
    accepted = d2.button("Accept with reason", use_container_width=True)
    escalated = d3.button("Escalate", use_container_width=True)

    if blocked or accepted or escalated:
        action = "block" if blocked else ("accept" if accepted else "escalate")
        _run_decision(variant_id, run, action)

    st.markdown(
        f'<div class="aa-provenance">'
        f'<b>Provenance.</b> Regions located by <code>{run["region_source"]}</code> '
        f"(normalised cross-correlation against the approved master) — not SAM 3.1, which "
        f"arrives when a Model API key is available. "
        f'Text read by <code>{run["text_source"]}</code>. '
        f'Video sampled at {run.get("sample_fps", 0):.0f} fps '
        f'({run.get("frame_count", 1)} frames examined). '
        f'Variant SHA-256 <code>{run["variant_sha256"][:16]}…</code>. '
        f'Checked in {run.get("seconds", 0):.1f}s.'
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------

elif screen == "Blast radius":
    st.title("Blast radius")
    _simulated_banner()
    st.write("")

    graph = load_graph()
    if graph is None:
        st.info("No lineage yet. Run:\n\n```\npython scripts/make_lineage.py\n```")
        st.stop()

    df = pd.DataFrame(RUN_ROWS)
    failing = df[df["fail"] > 0]
    if failing.empty:
        st.info("No failing variants in the cached run.")
        st.stop()

    variant_id = st.selectbox("Blocked variant", failing["variant_id"].tolist())
    try:
        result = graph.blast_radius(variant_id)
    except KeyError:
        st.warning("That variant is not attached to an ad in the lineage.")
        st.stop()

    c1, c2, c3 = st.columns([1, 1, 2])
    _metric(c1, result.feature, "enhancement that caused it")
    _metric(c2, str(result.count), "other live ads at risk", "aa-fail")
    c3.markdown(
        f'<div class="aa-metric aa-fail">{result.headline()}</div>'
        '<div class="aa-metric-sub">one approved decision, applied across the account</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        "Siblings must share the asset **and** be enrolled in the enhancement that did the "
        "damage. Sharing the asset alone over-reports: an ad that opted out of the feature is "
        "not at risk from it, and telling a reviewer to fix 40 ads when 14 are affected is how "
        "a tool loses their trust the first time they check it by hand."
    )

    st.markdown("#### The query")
    st.code(result.cypher, language="cypher")
    st.caption(
        f"Run against Neo4j when configured; here against the same graph in memory "
        f"(backend: `{result.backend}`), because a hosted demo must not be able to fail "
        "because a database is down."
    )

    if result.siblings:
        st.markdown("#### Ads that would be opted out")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "ad": s.ad_id,
                        "master": s.master_id,
                        "placement": s.placement,
                        "enrolment": s.enroll_status,
                        "already failing": s.already_failing,
                    }
                    for s in result.siblings
                ]
            ),
            use_container_width=True,
        )

    st.markdown("#### Act, then prove")
    st.caption(
        "Dry run by default — acting on a live ad account must never happen by omission. "
        "The Prove step re-reads settings and re-renders the preview; a finding only closes "
        "when both confirm, never because a request returned 200."
    )
    plan = plan_opt_out(
        [s.ad_id for s in result.siblings],
        result.feature,
        asset_id=result.asset_id,
        reason=f"blocked: {variant_id}",
    )
    st.code(json.dumps(plan.as_requests()[:3], indent=2), language="json")
    if plan.count > 3:
        st.caption(f"…and {plan.count - 3} more of the same shape.")

    proof = prove([s.ad_id for s in result.siblings], result.feature)
    st.dataframe(
        pd.DataFrame(
            [{"ad": p.ad_id, "status": p.status, "note": p.note} for p in proof]
        ),
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

elif screen == "Evidence":
    st.title("Evidence")
    _simulated_banner()
    st.write("")

    st.markdown("#### Hash-chained decision log")
    st.caption(
        "Append-only JSONL. Each record's digest covers the previous record's hash, its own "
        "index and its timestamp — so editing, reordering or deleting a record all break "
        "verification. Retention framed against COBS 4.11.1R: 3 years, 5 for MiFID business."
    )

    demo_log = settings.evidence_dir / "demo.jsonl"
    from asapproved.evidence import append_record, read_entries, verify_chain

    cols = st.columns([1, 1, 2])
    if cols[0].button("Build a sample log", use_container_width=True):
        demo_log.unlink(missing_ok=True)
        for i, decision in enumerate(["accept", "block", "accept", "escalate"]):
            append_record(
                demo_log,
                {
                    "variant_id": RUN_ROWS[min(i, len(RUN_ROWS) - 1)]["variant_id"],
                    "decision": decision,
                    "rule_ids": ["R4", "R8"] if decision == "block" else [],
                },
            )
        st.rerun()

    if demo_log.exists():
        if cols[1].button("Tamper with one record", use_container_width=True):
            text = demo_log.read_text(encoding="utf-8")
            demo_log.write_text(
                text.replace('"decision":"block"', '"decision":"accept"', 1), encoding="utf-8"
            )
            st.rerun()

        result = verify_chain(demo_log)
        if result.ok:
            st.success(f"INTACT — {result.entries} records, chain unbroken")
            st.caption(f"head `{result.head}`")
        else:
            st.error(f"TAMPERED — {result.reason}")
            st.caption(
                f"first bad record: index {result.first_bad_index}, line {result.first_bad_line}; "
                f"{result.entries} verified before the break"
            )

        rows = []
        for lineno, entry, _ in read_entries(demo_log):
            if entry is None:
                rows.append({"index": "?", "line": lineno, "record": "unparseable"})
                continue
            rows.append(
                {
                    "index": entry.index,
                    "ts": entry.ts,
                    "decision": entry.record.get("decision"),
                    "variant": entry.record.get("variant_id"),
                    "hash": entry.hash[:16] + "…",
                    "prev": entry.prev[:16] + "…",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

        st.caption(
            "Known limit, stated rather than hidden: a hash chain cannot detect records "
            "removed from the END. That needs an anchored head — a real deployment ships the "
            "head hash off-box daily."
        )
    else:
        st.info("No sample log yet.")


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

elif screen == "Benchmark":
    st.title("VariantBench-UK")
    _simulated_banner()
    st.write("")

    data = load_eval()
    if data is None:
        st.info(
            "No benchmark results yet. Run:\n\n```\npython scripts/run_bench.py\n```"
        )
    else:
        rows = []
        for rep in data["reports"]:
            def pct(v):
                return "—" if v is None else f"{v * 100:.0f}%"

            rows.append(
                {
                    "baseline": rep["name"],
                    "what it is": rep["description"],
                    "precision": pct(rep["precision"]),
                    "recall": pct(rep["recall"]),
                    "F1": pct(rep["f1"]),
                    "false-block rate": pct(rep["false_block_rate"]),
                    "scored": rep["variants_scored"],
                    "not evaluated": rep["variants_skipped"],
                    "s/variant": f"{rep['mean_seconds']:.1f}",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        st.caption(
            "B0 (Muse Spark alone) needs a Model API key and is reported as not run rather "
            "than as a zero. False-block rate is the share of benign variants wrongly "
            "flagged — a tool that blocks good ads gets switched off."
        )

        for rep in data["reports"]:
            per_rule = rep.get("per_rule") or {}
            if not any(v["tp"] + v["fp"] + v["fn"] for v in per_rule.values()):
                continue
            st.markdown(f"#### {rep['name']} — per rule")
            rr = []
            for rule_id, v in sorted(per_rule.items(), key=lambda kv: int(kv[0][1:])):
                rr.append(
                    {
                        "rule": rule_id,
                        "TP": v["tp"],
                        "FP": v["fp"],
                        "FN": v["fn"],
                        "precision": "—" if v["precision"] is None else f"{v['precision']*100:.0f}%",
                        "recall": "—" if v["recall"] is None else f"{v['recall']*100:.0f}%",
                        "not evaluated": v["not_evaluated"],
                    }
                )
            st.dataframe(pd.DataFrame(rr), use_container_width=True)


# ---------------------------------------------------------------------------
# Rulebook
# ---------------------------------------------------------------------------

elif screen == "Rulebook":
    st.title("Rulebook")
    _simulated_banner()
    st.write("")

    meta = load_rulebook_meta()
    c1, c2, c3 = st.columns(3)
    _metric(c1, meta["version"], "version")
    _metric(c2, meta["status"], "status", "aa-warn" if not meta["verified"] else "aa-ok")
    _metric(c3, str(len(meta["rules"])), "rules")

    if not meta["verified"]:
        st.warning(
            "This rulebook is marked **draft**: the citations have not all been re-checked "
            "against the live FCA handbook. Findings are flags for compliance review, not "
            "legal conclusions.",
            icon="⚠️",
        )

    st.dataframe(pd.DataFrame(meta["rules"]), use_container_width=True, height=520)
    st.caption(
        "The rulebook is data, not code: adding a jurisdiction is a YAML file, not a release. "
        "Thresholds (2% region change, 4.5:1 contrast, 98% visibility) are engineering "
        "choices, stated as such, not figures the FCA prescribes."
    )
