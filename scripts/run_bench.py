"""Run VariantBench-UK and write eval/report.md plus eval/results.json.

    python scripts/run_bench.py [--limit N] [--baselines pixel,asapproved]

A third baseline, Muse Spark alone, needs a Model API key and is reported as
"not run" rather than as a zero until one exists.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.config import settings  # noqa: E402
from asapproved.eval.harness import (  # noqa: E402
    load_labels,
    report_to_dict,
    run_b1,
    run_b2,
    score,
    write_report,
)

# Named once: the set is both the validator and the test for "was this a full
# run?". Those two were separate literals, and renaming the baselines updated one
# of them — every run then wrote eval/report.partial.md and left the published
# files alone. The guard did its job, but a single source of truth is the fix.
ALL_BASELINES = {"pixel", "asapproved"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Score only the first N variants.")
    parser.add_argument(
        "--baselines",
        default=",".join(sorted(ALL_BASELINES)),
        help="Comma-separated: pixel, asapproved. b1/b2 are accepted as the old names.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    labels_path = settings.labels_dir / "variantbench_uk.json"
    if not labels_path.exists():
        print(f"no labels at {labels_path} — run scripts/make_variants.py first", file=sys.stderr)
        return 1
    labels = load_labels(labels_path)
    if args.limit:
        labels = dict(labels, labels=labels["labels"][: args.limit])

    masters = settings.masters_dir
    variants = settings.variants_dir
    if not variants.is_dir() or not any(variants.glob("*.*")):
        print(
            f"no variants at {variants} — run:\n"
            "  python scripts/make_masters.py\n"
            "  python scripts/make_variants.py",
            file=sys.stderr,
        )
        return 1

    # `b1`/`b2` were the original selectors; the reports have been named
    # PIXEL/ASAPPROVED for a while, and a flag that still spoke the old
    # vocabulary was one more thing a judge would have to decode.
    aliases = {"b1": "pixel", "b2": "asapproved"}
    wanted = {aliases.get(b, b) for b in (x.strip().lower() for x in args.baselines.split(","))}
    unknown = wanted - ALL_BASELINES
    if unknown:
        print(f"unknown baseline(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 1
    reports = []

    if "pixel" in wanted:
        print("PIXEL — pixel diff alone ...", flush=True)
        t0 = time.time()
        preds = run_b1(labels, masters, variants)
        # Scored rule-aware, like the full pipeline. A pixel diff answers "did
        # something change?" and nothing else, so its per-rule row is the honest
        # measure of the gap: strong at detection, incapable of attribution.
        reports.append(score("PIXEL", "pixel diff alone", preds, labels))
        print(f"   done in {time.time() - t0:.0f}s")

    if "asapproved" in wanted:
        print("ASAPPROVED — full pipeline ...", flush=True)
        t0 = time.time()
        preds = run_b2(labels, masters, variants)
        reports.append(score("ASAPPROVED", "full pipeline", preds, labels))
        print(f"   done in {time.time() - t0:.0f}s")

    # A partial run writes to partial files. Letting `--limit 4` overwrite the
    # published 48-variant report made the README's headline numbers disagree
    # with the repo's own eval/report.md, which is the single most
    # credibility-destroying inconsistency this project could ship.
    out_dir = REPO_ROOT / "eval"
    partial = bool(args.limit) or wanted != ALL_BASELINES
    suffix = ".partial" if partial else ""
    if partial:
        print(f"\n  partial run -> eval/report{suffix}.md (published files untouched)")

    report_path = write_report(reports, out_dir / f"report{suffix}.md", labels)
    (out_dir / f"results{suffix}.json").write_text(
        json.dumps(
            {
                "labels_sha256": labels.get("labels_sha256"),
                "reports": [report_to_dict(r) for r in reports],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    for r in reports:

        def pct(v):
            return "—" if v is None else f"{v * 100:.0f}%"

        print(
            f"  {r.name}: precision {pct(r.precision)}  recall {pct(r.recall)}  "
            f"F1 {pct(r.f1)}  false-block {pct(r.false_block_rate)}  "
            f"scored {r.variants_scored}  skipped {r.variants_skipped}  "
            f"{r.mean_seconds:.1f}s/variant"
        )
    print(f"\n  report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
