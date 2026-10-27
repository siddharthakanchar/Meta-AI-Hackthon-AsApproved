"""Smoke tests for the review UI itself, driven through `streamlit.testing.v1`.

`test_app_data.py` covers the files the UI reads. These cover the UI: AppTest
executes the real script in-process, so a renderer that raises on a record
shape, a screen that stops early, or a decision button that no longer reaches
the evidence log fails here instead of in front of a judge.

The reason this matters more than it looks: every screen is guarded by
`st.stop()` on missing data, so a broken screen does not crash — it renders
blank and says nothing. That is the failure mode these tests exist to catch,
and the assertions are therefore about *what is on screen*, not merely about
the absence of an exception.
"""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from asapproved.config import REPO_ROOT, Settings, settings

APP = str(REPO_ROOT / "app" / "streamlit_app.py")
RUNS = settings.data_dir / "runs"
INDEX = RUNS / "index.json"

pytestmark = pytest.mark.skipif(
    not INDEX.exists(), reason="no precomputed runs; run scripts/precompute.py"
)

SCREENS = [
    "Variant review",
    "Overview",
    "Blast radius",
    "Evidence",
    "Benchmark",
    "Rulebook",
]


def _variant_ids() -> list[str]:
    if not INDEX.exists():
        return []
    return [r["variant_id"] for r in json.loads(INDEX.read_text(encoding="utf-8"))["runs"]]


@pytest.fixture()
def isolated_evidence(monkeypatch, tmp_path):
    """Point the evidence log at a temp dir.

    Clicking Block really appends to the chain — that is the point of the test —
    so without this the suite would write into the operator's own decision log,
    and the tamper test would corrupt the demo log they present from.
    """
    monkeypatch.setattr(Settings, "evidence_dir", property(lambda self: tmp_path))
    return tmp_path


@pytest.fixture()
def app(isolated_evidence):
    """A fresh app run, with Streamlit's caches cleared first.

    Every UI test gets the isolated evidence dir, not just the ones that click
    a decision button: the Evidence screen renders the *state* of the log, so a
    tampered or half-built real log would otherwise make unrelated tests fail.

    `load_index` and friends are `@st.cache_data`, and the cache outlives an
    AppTest instance within a process. Without clearing, a test that redirects
    `data_dir` would still be served the previous test's data.
    """
    import streamlit as st

    st.cache_data.clear()
    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    return at


def _click(at: AppTest, label: str) -> AppTest:
    labels = [b.label for b in at.button]
    assert label in labels, f"no {label!r} button; have {labels}"
    return at.button[labels.index(label)].click().run()


def _screen(at: AppTest, name: str) -> AppTest:
    at = at.sidebar.radio[0].set_value(name).run()
    assert not at.exception, (name, at.exception)
    return at


# ---------------------------------------------------------------- chrome ----


def test_sidebar_offers_every_screen(app):
    assert app.sidebar.radio[0].options == SCREENS


def test_sidebar_states_the_mode_and_the_label_digest(app):
    """A judge must be able to see, without asking, that nothing here was live."""
    captions = " ".join(c.value for c in app.sidebar.caption)
    assert "cached runs, no API calls" in captions
    digest = json.loads(INDEX.read_text(encoding="utf-8")).get("labels_sha256") or ""
    assert digest[:12] in captions


@pytest.mark.parametrize("screen", SCREENS)
def test_every_screen_renders_something(app, screen):
    at = _screen(app, screen)
    assert at.title, f"{screen} rendered no title"
    # A screen that bailed through st.stop() shows an error and little else.
    assert not at.error, [e.value for e in at.error]


def test_the_simulated_banner_is_on_every_screen(app):
    """Never present synthetic creative as real. That is a submission
    commitment, so it is pinned by test rather than left to whoever edits the
    page next."""
    for screen in SCREENS:
        at = _screen(app, screen)
        body = " ".join(m.value for m in at.markdown)
        assert "aa-sim" in body and "synthetic" in body, screen


# -------------------------------------------------------- variant review ----


def test_opens_on_the_hero_variant(app):
    """The demo has one shot at a first impression: the APR that animates off
    frame, not whichever variant happens to sort first."""
    assert app.title[0].value == "Variant review"
    assert "apr_animates" in app.selectbox[0].value


def test_hero_variant_shows_a_visibility_timeline(app):
    """The headline measurement is the share of frames a region was missing.
    If the bar stops rendering, the product's whole claim goes quiet."""
    body = " ".join(m.value for m in app.markdown)
    assert "on screen <b>" in body, "no visibility bar on the hero variant"
    captions = " ".join(c.value for c in app.caption)
    assert "Green = on screen, red = not" in captions


def test_hero_variant_names_its_sources(app):
    body = " ".join(m.value for m in app.markdown)
    assert "Provenance" in body
    assert "not SAM 3.1" in body, "the provenance block must not imply SAM ran"


def test_findings_and_a_validated_note_are_present(app):
    body = " ".join(m.value for m in app.markdown)
    assert "#### Findings" in body
    # Anchored on the attribute, not the bare class name: `aa-finding-head`
    # contains the substring and would satisfy a looser check.
    assert 'class="aa-finding"' in body, "findings rendered no cards"
    run = json.loads((RUNS / f"{app.selectbox[0].value}.json").read_text(encoding="utf-8"))
    assert any(c.value == run["note"] for c in app.code), "compliance note not on screen"


@pytest.mark.parametrize("variant_id", _variant_ids())
def test_every_cached_variant_renders(app, variant_id):
    """48 records, 48 different shapes — video and still, failing and benign,
    measured and inconclusive. One field a renderer does not expect is a blank
    panel, and this is the only thing that would catch it."""
    at = app.selectbox[0].set_value(variant_id).run()
    assert not at.exception, (variant_id, at.exception)
    assert at.title[0].value == "Variant review"
    body = " ".join(m.value for m in at.markdown)
    assert "Provenance" in body, variant_id


# -------------------------------------------------------------- decision ----


def test_block_runs_blast_radius_act_prove_and_evidence(app, isolated_evidence):
    at = _click(app, "Block")
    assert not at.exception, at.exception
    body = " ".join(m.value for m in at.markdown)
    for step in ("1 · Blast radius", "2 · Act", "3 · Prove", "4 · Evidence"):
        assert step in body, f"{step} missing from the decision loop"

    assert any("chain INTACT" in s.value for s in at.success), [s.value for s in at.success]

    log = isolated_evidence / "decisions.jsonl"
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["record"]["decision"] == "block"
    assert entry["record"]["dry_run"] is True, "the UI must never act for real"
    assert entry["record"]["siblings_opted_out"] >= 1
    assert entry["prev"] == "0" * 64


def test_prove_never_reports_a_fix_it_did_not_watch_land(app, isolated_evidence):
    """Without Marketing API access nothing was observed. Reporting these rows
    as proven would make the whole evidence trail worthless."""
    at = _click(app, "Block")
    captions = " ".join(c.value for c in at.caption)
    assert "could not verify" in captions
    assert "not *proven*" in captions


@pytest.mark.parametrize(
    "label,decision", [("Accept with reason", "accept"), ("Escalate", "escalate")]
)
def test_accept_and_escalate_record_without_opting_anything_out(
    app, isolated_evidence, label, decision
):
    at = _click(app, label)
    assert not at.exception, at.exception
    entry = json.loads(
        (isolated_evidence / "decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert entry["record"]["decision"] == decision
    assert entry["record"]["siblings_opted_out"] == 0, "only a block opts siblings out"


# -------------------------------------------------------------- evidence ----


def test_evidence_screen_builds_a_chain_then_detects_tampering(app, isolated_evidence):
    at = _screen(app, "Evidence")
    at = _click(at, "Build a sample log")
    assert any("INTACT" in s.value for s in at.success), [s.value for s in at.success]

    at = _click(at, "Tamper with one record")
    assert at.error, "a tampered chain still verified"
    assert "TAMPERED" in at.error[0].value
    captions = " ".join(c.value for c in at.caption)
    assert "removed from the END" in captions, "the known limit of a hash chain must stay on screen"


# ------------------------------------------------------------- benchmark ----


def test_benchmark_screen_reports_per_rule_and_calls_b0_not_run(app):
    at = _screen(app, "Benchmark")
    assert len(at.dataframe) >= 2, "per-rule table missing"
    captions = " ".join(c.value for c in at.caption)
    assert "not run" in captions, "a model that never ran must not read as a zero"


# -------------------------------------------------------------- rulebook ----


def test_rulebook_screen_warns_while_the_citations_are_unverified(app):
    from asapproved.rules.engine import load_rulebook

    if load_rulebook().verified:
        pytest.skip("rulebook is now verified; the draft warning is correctly absent")
    at = _screen(app, "Rulebook")
    assert at.warning, "a draft rulebook rendered no warning"
    assert "not legal conclusions" in at.warning[0].value


# --------------------------------------------------------------- no data ----


def test_without_cached_runs_the_app_says_how_to_build_them(monkeypatch, tmp_path):
    """The hosted demo's worst failure is a blank page. If the runs are missing,
    the app must name the three scripts that produce them."""
    import streamlit as st

    # `data_dir` is a dataclass field, so there is no class attribute to replace;
    # a class-level property still wins over the instance dict, and raising=False
    # lets us install one.
    monkeypatch.setattr(Settings, "data_dir", property(lambda self: tmp_path), raising=False)
    st.cache_data.clear()
    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    assert at.title[0].value == "AsApproved"
    assert at.error, "no runs, and no error message either"
    msg = at.error[0].value
    for script in ("make_masters.py", "make_variants.py", "precompute.py"):
        assert script in msg, script
