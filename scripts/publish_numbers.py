"""Render every published number from `eval/results.json`, so none is typed by hand.

    python scripts/publish_numbers.py            # rewrite the generated blocks
    python scripts/publish_numbers.py --check    # fail if any block is stale

Three documents quote the benchmark: the README, `docs/DECISIONS.md` and
`submission/SUBMISSION.md`. Keeping them in agreement by hand failed twice
during this build — once leaving the README a benchmark run behind, once
leaving a test count in `docs/STATUS.md` that had never been measured at all.
A number that disagrees with the repo's own `eval/report.md` is the most
credibility-destroying thing this project could ship, so the blocks are
generated and `--check` is wired into the test suite.

Each generated region is delimited by HTML comments, invisible in rendered
Markdown. Edit the surrounding prose freely; anything between the markers will
be overwritten.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import math
import pathlib
import sys
import textwrap

WRAP = 78

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Last verified by rebuilding the dataset in a clean clone of the committed
# tree and comparing against this working copy. Both are stated because they
# are different claims: the labels agreeing means a judge scores against the
# same answer key, while the assets agreeing byte for byte means the generator
# itself is deterministic, down to the H.264 encode.
REPRO_VERIFIED = "27 Oct 2026"
REPRO_ASSETS = 60


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def rewrap(text: str, width: int = WRAP) -> str:
    """Re-wrap prose paragraphs, leaving tables, headings and lists alone.

    Interpolating measurements into hand-wrapped prose leaves ragged lines —
    one short, the next 140 characters long — and the diff for a changed
    number then spans the whole paragraph. Wrapping afterwards means the diff
    shows the sentences that actually changed. Markdown treats a single newline
    as a space, so this changes nothing about how the page renders.
    """
    out: list[str] = []
    para: list[str] = []
    fenced = False

    def flush() -> None:
        if para:
            out.extend(
                textwrap.wrap(
                    " ".join(para),
                    width=width,
                    break_long_words=False,
                    # "3 audio-dependent" must not become "3 audio-" / "dependent".
                    break_on_hyphens=False,
                )
            )
            para.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            fenced = not fenced
            out.append(line)
            continue
        # A bullet needs the space: `**Where it is weak.**` opens a paragraph,
        # not a list, and treating it as one left the whole paragraph unwrapped.
        bullet = stripped[:2] in ("- ", "* ", "> ") or stripped in ("-", "*", ">")
        verbatim = fenced or bullet or stripped.startswith(("|", "#")) or line.startswith("    ")
        if not stripped or verbatim:
            flush()
            out.append(line)
            continue
        para.append(stripped)
    flush()
    return "\n".join(out)


def _binom_cdf(x: int, n: int, p: float) -> float:
    return sum(math.comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(x + 1))


def clopper_pearson_upper(x: int, n: int, alpha: float = 0.05) -> float:
    """Exact two-sided upper confidence bound for a binomial rate.

    Written out rather than taken from scipy: scipy is only present here as a
    transitive dependency of scikit-image, and a published confidence interval
    should not rest on a package this project never declared.
    """
    if n == 0:
        return 1.0
    if x >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _binom_cdf(x, n, mid) > alpha / 2:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


WHAT = {
    "R1": "claim region materially changed",
    "R3": "warning removed or clipped",
    "R4": "on screen throughout (video)",
    "R5": "bordered, bold, underlined",
    "R6": "contrast below threshold",
    "R7": "smaller than body copy",
    "R8": "APR prominence vs trigger",
    "R9": "trigger spoken, APR not",
    "R10": "cost figure, no example",
    "R11": "prescribed wording altered",
    "R12": "inside the platform UI zone",
}


class Figures:
    """Everything the documents are allowed to quote, read once from disk."""

    def __init__(self) -> None:
        self.res = json.loads((REPO_ROOT / "eval" / "results.json").read_text(encoding="utf-8"))
        self.labs = json.loads(
            (REPO_ROOT / "data" / "labels" / "variantbench_uk.json").read_text(encoding="utf-8")
        )
        by_name = {r["name"]: r for r in self.res["reports"]}
        self.pixel = by_name["PIXEL"]
        self.full = by_name["ASAPPROVED"]
        self.digest = self.labs["labels_sha256"]

        self.derived: collections.Counter[str] = collections.Counter()
        self.intended: collections.Counter[str] = collections.Counter()
        self.audio = 0
        for lab in self.labs["labels"]:
            self.derived.update(lab["violated_rules"])
            self.intended.update(lab.get("intended_rules", []))
            self.audio += bool(lab["requires_audio"])

        self.benign_total = self.full["fp"] + self.full["tn"]
        self.fb_upper = clopper_pearson_upper(self.full["fp"], self.benign_total)

        self.weak = sorted(
            (
                (rid, v)
                for rid, v in self.full["per_rule"].items()
                if v["precision"] is not None and v["precision"] < 1.0
            ),
            key=lambda kv: kv[1]["precision"],
        )
        self.missing = sorted(
            (rid for rid, v in self.full["per_rule"].items() if v["fn"]),
            key=lambda r: int(r[1:]),
        )
        self.unmeasured = sorted(
            (
                rid
                for rid, v in self.full["per_rule"].items()
                if v["not_evaluated"] and not (v["tp"] + v["fp"] + v["fn"])
            ),
            key=lambda r: int(r[1:]),
        )
        self.rules = [
            f"R{n}" for n in range(1, 13) if f"R{n}" in self.derived or f"R{n}" in self.intended
        ]

    # ---------------------------------------------------------------- bits --

    def per_rule_rows(self) -> str:
        rows = []
        for rid, v in sorted(self.full["per_rule"].items(), key=lambda kv: int(kv[0][1:])):
            b = "**" if rid in self.unmeasured else ""
            cells = [
                rid,
                WHAT.get(rid, ""),
                pct(v["precision"]),
                pct(v["recall"]),
                str(v["tp"]),
                str(v["fp"]),
                str(v["fn"]),
                str(v["not_evaluated"]),
            ]
            rows.append("| " + " | ".join(f"{b}{c}{b}" for c in cells) + " |")
        return "\n".join(rows)

    def variant_table(self) -> str:
        p, f = self.pixel, self.full
        return (
            "| Baseline | Precision | Recall | F1 | False blocks | s/variant |\n"
            "|---|---|---|---|---|---|\n"
            f"| Pixel diff alone | {pct(p['precision'])} | {pct(p['recall'])} | "
            f"{pct(p['f1'])} | {p['fp']}/{p['fp'] + p['tn']} | {p['mean_seconds']:.1f} |\n"
            f"| **AsApproved** | {pct(f['precision'])} | {pct(f['recall'])} | "
            f"{pct(f['f1'])} | {f['fp']}/{self.benign_total} | {f['mean_seconds']:.1f} |\n"
            "| Muse Spark alone | not run — needs an API key | | | | |"
        )

    def weak_sentence(self) -> str:
        """Prose about the weakest rules, phrased so it survives the numbers changing.

        An earlier version read "below 100% on R5, R7, and R12 is the only rule
        that also misses", which parses as a three-item list. If every rule ever
        reaches 100% this has to stop claiming otherwise, so both halves are
        conditional.
        """
        if not self.weak and not self.missing:
            return (
                "**Where it is weak.** Every measured rule is at 100% precision and "
                "recall on this set — which, on a development set this small, is a "
                "statement about the set as much as about the detector."
            )
        parts = []
        if self.weak:
            names = ", ".join(f"{r} ({pct(v['precision'])})" for r, v in self.weak)
            parts.append(f"Precision is below 100% on {names}")
        for rid in self.missing:
            v = self.full["per_rule"][rid]
            parts.append(
                f"**{rid} is the only rule that also misses** ({pct(v['recall'])} "
                f"recall, {v['fn']} false negative)"
                if len(self.missing) == 1
                else f"{rid} misses {v['fn']}"
            )
        return "**Where it is weak.** " + ", and ".join(parts) + "."


# ------------------------------------------------------------------ blocks --


def readme_block(g: Figures) -> str:
    r1_derived = g.derived.get("R1", 0)
    r1_intended = g.intended.get("R1", 0)
    return f"""VariantBench-UK: 12 approved masters → 48 variants ({g.labs["violations"]} seeded
violations, {g.labs["benign"]} benign edits). Ground truth is **computed, not
hand-written**: every rule a variant breaks is derived from what the generator
drew — the RGB values it chose, the font scale it set, the box coordinates it
placed. Nothing in the label pipeline reads a pixel or calls the rules engine,
so a bug in the detector cannot launder itself into the answer key.

**Read the per-rule table first.** The variant-level score answers the easy
question.

### Per-rule attribution

| Rule | What it checks | Precision | Recall | TP | FP | FN | Not evaluated |
|---|---|---|---|---|---|---|---|
{g.per_rule_rows()}

A pixel-diff baseline scores **0% recall on every rule except R1** — asserting
"something changed" is the only thing it can do.

**{len(g.unmeasured) + 1} of 12 rules carry no measured evidence.** R2 compares
live API settings against the manifest and has no pixel expression, so it is
excluded from every vision baseline. R9 needs a transcript, and the
{g.audio} audio-dependent variants carry no audio track — the voiceovers in
`data/masters/audio/` were generated but never muxed into the assets, and no
transcriber has run either way. R10 needs Muse Spark claim extraction.
{12 - len(g.unmeasured) - 1} rules were measured.

{g.weak_sentence()} These are localisation errors rather than logic errors: the
tracker's box is close but not exact, so a neighbouring rule occasionally trips
with the right one. SAM 3.1 exists to close that gap, and region IoU is how we
will measure whether it does.

### Variant-level detection

{g.variant_table()}

{g.full["variants_scored"]} of 48 variants scored; {g.full["variants_skipped"]} need
audio. **{g.full["fp"]}/{g.benign_total} false blocks has an exact 95% upper bound of
{g.fb_upper * 100:.0f}%** — it is a small synthetic benign set (hue shift, brightness,
re-encode, margin trim, touch-up), not Meta's generative enhancements.

**These are development-set numbers.** The 48 variants are the set the detector
was debugged and calibrated against: the R1 area floor, the SSIM floor and the
OCR similarity bands were all fitted by measuring these populations. There is no
held-out split. {pct(g.full["f1"])} on the set you tuned on is weak evidence of
generalisation, and it should be read that way.

**R1 is satisfied by construction on {r1_derived} of {g.labs["violations"]} seeded
violations** — any seeded edit changes a claim region — so it carries most of
the variant-level recall. Only {r1_intended} variants were *designed* to test
it. The label file records both `intended_rules` and `violated_rules`.

**Reproducible, bit for bit.** Rebuilding the dataset in a clean clone of the
committed tree reproduces the label digest `{g.digest[:16]}…` *and* all
{REPRO_ASSETS} generated assets byte for byte, H.264 encodes included — verified
{REPRO_VERIFIED}. A judge who rebuilds is scoring the same files against the same
answer key these numbers came from.

Full report: [`eval/report.md`](eval/report.md). Regenerate with
`asapproved bench`, then `python scripts/publish_numbers.py` to update every
document that quotes it."""


def decisions_block(g: Figures) -> str:
    return f"""## VariantBench-UK coverage ({g.labs["count"]} variants)

Ground truth is DERIVED — every rule a variant actually breaks, computed from what the generator
drew. The transform's own declaration is kept as `intended_rules` so the difference is visible.

| | {" | ".join(g.rules)} |
|---|{"---|" * len(g.rules)}
| **derived** (ground truth) | {" | ".join(str(g.derived.get(r, 0)) for r in g.rules)} |
| **intended** (by design) | {" | ".join(str(g.intended.get(r, 0)) for r in g.rules)} |

The gap on R1 is not an error: any seeded edit to a claim region materially changes it, so R1 is
true by construction on {g.derived.get("R1", 0)} of {g.labs["violations"]} violations while only
{g.intended.get("R1", 0)} were designed to test it. That is why the per-rule table, not the
variant-level score, is the honest measure — and why the README leads with it.

{g.audio} variants are audio-dependent and carry no audio track, so they are reported as
**not evaluated**, never as passes, and their rules appear in the not-evaluated column rather
than vanishing from the table.

Label digest for this build: `{g.digest}`.

**The labels are NOT frozen, and that matters.** They and the detector were both changed during
development. Roughly half the apparent "detector failures" in this project turned out to be
defects in the benchmark itself — which is a good argument for deriving labels and a bad argument
for treating these numbers as a held-out evaluation. The rulebook also remains `status: draft`
with `sources_checked: null`. Published results are development-set results and the README says so.

**Last measured run.** AsApproved {pct(g.full["precision"])}/{pct(g.full["recall"])}/{pct(g.full["f1"])}
(precision/recall/F1) at variant level with {g.full["fp"]}/{g.benign_total} false blocks, against a
pixel diff at {pct(g.pixel["precision"])}/{pct(g.pixel["recall"])}/{pct(g.pixel["f1"])} and
{g.pixel["fp"]}/{g.pixel["fp"] + g.pixel["tn"]}. Per-rule, the weakest are
{", ".join(f"{r} ({pct(v['precision'])} precision)" for r, v in g.weak) or "none — all measured rules are at 100% precision"}.
{(", ".join(g.missing) + " " + ("is" if len(g.missing) == 1 else "are") + " the only rule(s) with a false negative.") if g.missing else "No measured rule has a false negative."}
"""


def _cell(stats: dict | None) -> str:
    """One baseline's per-rule result, or an explicit "not evaluated"."""
    if stats is None:
        return "—"
    if not (stats["tp"] + stats["fp"] + stats["fn"]):
        return "not evaluated"
    return (
        f"{pct(stats['precision'])} / {pct(stats['recall'])} "
        f"({stats['tp']}, {stats['fp']}, {stats['fn']})"
    )


def submission_block(g: Figures) -> str:
    p, f = g.pixel, g.full
    rule_rows = "\n".join(
        f"| {rid} — {WHAT.get(rid, '')} | {_cell(v)} | {_cell(p['per_rule'].get(rid))} |"
        for rid, v in sorted(f["per_rule"].items(), key=lambda kv: int(kv[0][1:]))
    )
    return f"""| Baseline | Precision | Recall | F1 | False blocks | s/variant |
|---|---|---|---|---|---|
| Pixel diff alone | {pct(p["precision"])} | {pct(p["recall"])} | {pct(p["f1"])} | {p["fp"]}/{p["fp"] + p["tn"]} | {p["mean_seconds"]:.1f} |
| **AsApproved** | {pct(f["precision"])} | {pct(f["recall"])} | {pct(f["f1"])} | {f["fp"]}/{g.benign_total} | {f["mean_seconds"]:.1f} |
| Muse Spark alone | not run — needs an API key | | | | |

Per rule, where the two separate — precision / recall (TP, FP, FN):

| Rule | AsApproved | Pixel diff |
|---|---|---|
{rule_rows}

The pixel baseline is charged a miss on rules it cannot attempt, because it
asserts the variant is clean; AsApproved reports *not evaluated* where it has no
evidence. That asymmetry is the design, not a scoring trick: a definite wrong
answer and an honest "could not measure" are different outcomes.

{f["variants_scored"]} of 48 variants scored, {f["variants_skipped"]} audio-dependent and
reported as not evaluated. {f["fp"]}/{g.benign_total} benign variants wrongly flagged (exact
95% upper bound {g.fb_upper * 100:.0f}%). Label digest `{g.digest[:16]}…`; a clean-clone rebuild
reproduces it and all {REPRO_ASSETS} generated assets byte for byte, verified {REPRO_VERIFIED}.
Development-set numbers — thresholds were fitted on these 48 variants and there is no held-out
split."""


def video_block(g: Figures) -> str:
    """The figures that get read aloud on camera.

    These were the worst stale numbers in the repo — the table still said R7 was
    at 50% and R12 at 57% two benchmark runs after both had moved, and it is the
    one place where a wrong number is spoken on a recording rather than quietly
    printed. Generated for that reason.
    """
    measured = [
        rid
        for rid, v in sorted(g.full["per_rule"].items(), key=lambda kv: int(kv[0][1:]))
        if rid not in g.unmeasured
    ]
    full_recall = [rid for rid in measured if g.full["per_rule"][rid]["recall"] == 1.0]
    if len(full_recall) == len(measured):
        recall_cell = f"100% on all {len(measured)} measured rules"
    else:
        short = ", ".join(
            f"{rid} {pct(g.full['per_rule'][rid]['recall'])}"
            for rid in measured
            if rid not in full_recall
        )
        recall_cell = (
            f"100% on {len(full_recall)} of {len(measured)} measured rules — except {short}"
        )
    weak_cell = (
        ", ".join(f"{rid} {pct(v['precision'])}" for rid, v in g.weak)
        or "none below 100% on this set"
    )
    unmeasured_cell = (
        ", ".join(
            f"{rid} ({g.full['per_rule'][rid]['not_evaluated']} variants)" for rid in g.unmeasured
        )
        + ", plus R2 which has no pixel expression"
    )
    return f"""| | |
|---|---|
| Hero case | APR on screen ~1s of 15s |
| Blast radius | whatever the screen shows for that variant |
| Variant level | {pct(g.full["precision"])} precision / {pct(g.full["recall"])} recall / {pct(g.full["f1"])} F1, {g.full["fp"]}/{g.benign_total} false blocks |
| Per-rule recall | {recall_cell} |
| Weakest precision | {weak_cell} |
| Pixel-diff baseline | {pct(g.pixel["f1"])} F1 at variant level, 0% recall on every rule but R1 |
| Not evaluated | {unmeasured_cell} |
| Speed | {g.full["mean_seconds"]:.1f}s per variant, against {g.pixel["mean_seconds"]:.1f}s for the pixel diff |"""


# ------------------------------------------------------------------ driver --

START = "<!-- publish_numbers:{} start — generated, do not edit by hand -->"
END = "<!-- publish_numbers:{} end -->"

TARGETS = [
    ("README.md", "readme", readme_block),
    ("docs/DECISIONS.md", "decisions", decisions_block),
    ("submission/SUBMISSION.md", "submission", submission_block),
    ("submission/VIDEO.md", "video", video_block),
]


def read_text_keeping_newlines(path: pathlib.Path) -> tuple[str, str]:
    """Read a file and report which newline it uses.

    This repo has no `.gitattributes` and holds a mix of LF and CRLF files.
    Writing with Python's default text mode turns every newline into CRLF on
    Windows, which flipped two LF files wholesale and buried a 16-line change
    in a 353-line diff. The style a file already uses is the style it keeps.
    """
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return raw.decode("utf-8").replace("\r\n", "\n"), newline


def render(g: Figures) -> list[tuple[pathlib.Path, str, str]]:
    """Return (path, whole file as it is, whole file as it should be).

    Both strings use "\\n" so a comparison never turns on line endings; the
    writer puts the file's own newline back.
    """
    out = []
    for rel, key, fn in TARGETS:
        path = REPO_ROOT / rel
        text, _newline = read_text_keeping_newlines(path)
        start, end = START.format(key), END.format(key)
        if start not in text or end not in text:
            raise SystemExit(
                f"{rel} has no publish_numbers:{key} markers — add them around the "
                "generated block, or this script cannot keep it honest."
            )
        head, _, rest = text.partition(start)
        _body, _, tail = rest.partition(end)
        wanted = head + f"{start}\n\n{rewrap(fn(g)).strip()}\n\n{end}" + tail
        out.append((path, text, wanted))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if any published number is stale.",
    )
    args = ap.parse_args()

    g = Figures()
    stale = []
    for path, current, wanted in render(g):
        if current == wanted:
            continue
        stale.append(path)
        if args.check:
            print(f"--- stale: {path.relative_to(REPO_ROOT)}", file=sys.stderr)
            diff = difflib.unified_diff(
                current.splitlines(), wanted.splitlines(), "published", "measured", lineterm=""
            )
            for line in list(diff)[:40]:
                print(line, file=sys.stderr)
        else:
            _, newline = read_text_keeping_newlines(path)
            path.write_bytes(wanted.replace("\n", newline).encode("utf-8"))

    if args.check:
        if stale:
            print(
                f"\n{len(stale)} document(s) disagree with eval/results.json. "
                "Run: python scripts/publish_numbers.py",
                file=sys.stderr,
            )
            return 1
        print("every published number agrees with eval/results.json")
        return 0

    print(f"updated {len(stale)} of {len(TARGETS)} documents from eval/results.json")
    print(f"  digest  {g.digest[:16]}…")
    print(f"  weakest {', '.join(r for r, _ in g.weak) or 'none'}")
    print(f"  misses  {', '.join(g.missing) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
