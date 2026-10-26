"""Phase 3 — build the 48 VariantBench-UK variants with automatic ground truth.

    python scripts/make_variants.py [--stills-only] [--master <id>]

Four variants per master: two seeded violations, two benign edits. 24 and 24.

Ground truth is derived by pushing each region's mask through the same transform
that produced the variant, so the labels cannot disagree with the pixels. Where a
transform also declares its expected visibility, the two are cross-checked and a
mismatch aborts the build — that is the generator testing itself rather than
restating itself.

Labels are written to data/labels/variantbench_uk.json with a hash over their
canonical form. Freeze that hash in DECISIONS.md before the first scored run.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.config import settings  # noqa: E402
from asapproved.synth.specs import MASTERS  # noqa: E402
from asapproved.synth.transforms import VariantPlan, transforms_for  # noqa: E402
from asapproved.synth.variants import build_variant, write_labels  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stills-only", action="store_true", help="Skip video masters.")
    parser.add_argument("--master", help="Only build variants of this master.")
    args = parser.parse_args()

    specs = MASTERS
    if args.master:
        specs = [s for s in specs if s.id == args.master]
        if not specs:
            print(f"no such master: {args.master}", file=sys.stderr)
            return 1
    if args.stills_only:
        specs = [s for s in specs if s.kind == "still"]

    out_dir = settings.variants_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    labels: list[dict] = []
    started = time.time()

    for spec in specs:
        for index, transform in enumerate(transforms_for(spec)):
            plan = VariantPlan(master=spec, transform=transform, index=index)
            t0 = time.time()

            def progress(done: int, total: int, vid: str = plan.variant_id) -> None:
                if done % 100 == 0 or done == total:
                    print(f"\r  {vid}: {done}/{total}", end="", flush=True)

            result = build_variant(
                plan, out_dir, progress=progress if spec.kind == "video" else None
            )
            labels.append(result.label)
            if spec.kind == "video":
                print("\r" + " " * 80, end="\r")

            tag = "benign " if transform.benign else "VIOLATE"
            rules = ",".join(transform.rules) or "-"
            print(
                f"  [{tag}] {plan.variant_id}"
                f"\n           rules={rules}  feature={transform.enhancement}"
                f"  [{time.time() - t0:.1f}s]"
            )

    labels_path = write_labels(labels, settings.labels_dir / "variantbench_uk.json")

    violations = sum(1 for lab in labels if not lab["benign"])
    print(f"\n{len(labels)} variants in {out_dir}  [{time.time() - started:.1f}s]")
    print(f"  {violations} seeded violations / {len(labels) - violations} benign")
    print(f"  labels: {labels_path}")

    import json

    doc = json.loads(labels_path.read_text(encoding="utf-8"))
    print(f"  labels_sha256: {doc['labels_sha256']}")
    print("\nRecord that hash in DECISIONS.md to freeze the label set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
