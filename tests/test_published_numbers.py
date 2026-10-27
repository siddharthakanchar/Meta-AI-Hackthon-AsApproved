"""Every number in the README, DECISIONS and SUBMISSION must match eval/results.json.

This existed as a claim before it existed as a test. The README said the
results were generated rather than transcribed, while the generator lived in a
scratch directory outside the repo — so the claim could not be checked by
anyone, including the next session, which is exactly how `docs/STATUS.md` came
to publish a test count that had never been measured.

`scripts/publish_numbers.py --check` is the enforcement. This wires it into
`pytest` so a benchmark run that is not followed by a regeneration fails here
rather than in front of a judge.
"""

from __future__ import annotations

import importlib.util
import json

import pytest

from asapproved.config import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "publish_numbers.py"
RESULTS = REPO_ROOT / "eval" / "results.json"


def _load():
    spec = importlib.util.spec_from_file_location("publish_numbers", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


@pytest.mark.skipif(not RESULTS.exists(), reason="no benchmark results; run asapproved bench")
def test_published_numbers_match_the_benchmark(mod):
    """The one that matters: no document may disagree with the measured run."""
    figures = mod.Figures()
    stale = [
        path.relative_to(REPO_ROOT).as_posix()
        for path, current, wanted in mod.render(figures)
        if current != wanted
    ]
    assert not stale, (
        f"{stale} disagree with eval/results.json — run: python scripts/publish_numbers.py"
    )


@pytest.mark.skipif(not RESULTS.exists(), reason="no benchmark results; run asapproved bench")
def test_the_reported_digest_is_the_committed_digest(mod):
    """A results file scored against one answer key and a label file holding
    another is the one inconsistency that would invalidate everything."""
    figures = mod.Figures()
    labels = json.loads(
        (REPO_ROOT / "data" / "labels" / "variantbench_uk.json").read_text(encoding="utf-8")
    )
    assert figures.digest == labels["labels_sha256"]
    index = REPO_ROOT / "data" / "runs" / "index.json"
    if index.exists():
        cached = json.loads(index.read_text(encoding="utf-8")).get("labels_sha256")
        if cached:
            assert cached == labels["labels_sha256"], (
                "the cached runs the UI reads were produced against a different label set"
            )


@pytest.mark.parametrize(
    "x,n,expected",
    [
        (0, 23, 14.819),
        (1, 23, 21.949),
        (3, 45, 18.268),
        (0, 10, 30.850),
    ],
)
def test_clopper_pearson_matches_the_reference_values(mod, x, n, expected):
    """Checked against `scipy.stats.beta.ppf(0.975, x+1, n-x)` to 3 decimals.

    The bound is written out by hand because scipy is only a transitive
    dependency here; these values are what pin that reimplementation.
    """
    assert mod.clopper_pearson_upper(x, n) * 100 == pytest.approx(expected, abs=1e-3)


def test_an_empty_denominator_does_not_claim_a_bound(mod):
    assert mod.clopper_pearson_upper(0, 0) == 1.0


def test_a_default_bench_run_is_not_treated_as_partial():
    """Renaming the baselines left `partial` comparing against the old names.

    Every run then silently wrote `eval/report.partial.md` and left the
    published report untouched — the guard protecting the published numbers
    fired on a full run. Cheap to assert, and it pins the one invariant that
    links the flag's default to the partial-run test.
    """
    spec = importlib.util.spec_from_file_location(
        "run_bench", REPO_ROOT / "scripts" / "run_bench.py"
    )
    assert spec and spec.loader
    run_bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_bench)

    default = run_bench.build_parser().parse_args([]).baselines
    wanted = {b.strip().lower() for b in default.split(",")}
    assert wanted == run_bench.ALL_BASELINES, (
        f"the default --baselines ({default!r}) does not select every baseline, so a "
        "plain `asapproved bench` would write only partial files"
    )

    # And the retired names still select the same two, so an old command works.
    aliases = {"b1": "pixel", "b2": "asapproved"}
    assert {aliases[b] for b in ("b1", "b2")} == run_bench.ALL_BASELINES


def test_the_generator_keeps_each_file_s_newline_style(mod, tmp_path):
    """This repo has no `.gitattributes` and mixes LF and CRLF. Writing with
    Python's default text mode converted two LF files wholesale, turning a
    16-line change into a 353-line diff nobody could review."""
    for newline in (b"\n", b"\r\n"):
        path = tmp_path / f"sample{len(newline)}.md"
        path.write_bytes(newline.join([b"one", b"two", b""]))
        text, detected = mod.read_text_keeping_newlines(path)
        assert detected == newline.decode()
        assert "\r" not in text, "the comparison text must be newline-neutral"


def test_rewrap_leaves_tables_and_code_alone(mod):
    source = (
        "A paragraph that is quite long and ought to be re-wrapped by the "
        "helper because it exceeds the configured width comfortably.\n"
        "\n"
        "| a | b |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "\n"
        "```\n"
        "a line of code that is deliberately far longer than the wrap width to prove it survives\n"
        "```\n"
        "\n"
        "- a bullet that is also longer than the wrap width and must stay on its own single line\n"
    )
    out = mod.rewrap(source, width=40)
    assert "| a | b |" in out.splitlines()
    assert any(line.startswith("- a bullet") and len(line) > 40 for line in out.splitlines())
    assert any("far longer than the wrap width" in line for line in out.splitlines())
    prose = out.split("\n\n")[0].splitlines()
    assert len(prose) > 1, "the long paragraph was not wrapped"
    assert all(len(line) <= 40 for line in prose)


def test_rewrap_wraps_a_paragraph_that_opens_in_bold(mod):
    """`**Where it is weak.**` is a paragraph, not a list item. Treating a
    leading `*` as a bullet left that whole paragraph on one 180-column line."""
    source = "**Bold opener.** " + "word " * 40
    out = mod.rewrap(source, width=40)
    assert len(out.splitlines()) > 1
