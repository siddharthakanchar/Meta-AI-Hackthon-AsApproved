"""Run VariantBench-UK and write eval/report.md plus eval/results.json.

    python scripts/run_bench.py [--limit N] [--baselines b1,b2]

B0 (Spark alone) needs a Model API key and is reported as "not run" rather than
as a zero until one exists.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Score only the first N variants.")
    parser.add_argument("--baselines", default="b1,b2")
    args = parser.parse_args()

    labels_path = settings.labels_dir / "variantbench_uk.json"
    if not labels_path.exists():
        print(f"no labels at {labels_path} — run scripts/make_variants.py first", file=sys.stderr)
        return 1
    labels = load_labels(labels_path)
    if args.limit:
        labels = dict(labels, labels=labels["labels"][: args.limit])

    masters = settings.masters_dir
    variants = settings.variants_dir
    wanted = {b.strip().lower() for b in args.baselines.split(",")}
    reports = []

    if "b1" in wanted:
        print("B1 — pixel diff alone ...", flush=True)
        t0 = time.time()
        preds = run_b1(labels, masters, variants)
        # Scored rule-aware, like B2. A pixel diff answers "did something
        # change?" and nothing else, so its per-rule row is the honest measure
        # of the gap: strong at detection, incapable of attribution.
        reports.append(score("B1", "pixel diff alone", preds, labels))
        print(f"   done in {time.time() - t0:.0f}s")

    if "b2" in wanted:
        print("B2 — AsApproved full pipeline ...", flush=True)
        t0 = time.time()
        preds = run_b2(labels, masters, variants)
        reports.append(score("B2", "AsApproved", preds, labels))
        print(f"   done in {time.time() - t0:.0f}s")

    out_dir = REPO_ROOT / "eval"
    report_path = write_report(reports, out_dir / "report.md", labels)
    (out_dir / "results.json").write_text(
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
