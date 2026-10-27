"""Phase 3 — build the 12 approved masters.

    python scripts/make_masters.py [--only <id>] [--stills-only]

Three fictional UK firms, original logos from plain geometry, no real brands and
no real people. Each master is compliant by construction: the prescribed warning
or representative example at proper prominence, in its own bordered box, bold and
underlined, at high contrast — because the master is what "approved" means, and a
baseline that quietly broke the rules would make every later measurement
meaningless.

Prescribed wording comes from the rulebook, not from this file.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.config import settings  # noqa: E402
from asapproved.synth.build import build_master  # noqa: E402
from asapproved.synth.specs import MASTERS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Build a single master by id.")
    parser.add_argument("--stills-only", action="store_true", help="Skip videos (no ffmpeg).")
    args = parser.parse_args()

    specs = MASTERS
    if args.only:
        specs = [s for s in specs if s.id == args.only]
        if not specs:
            print(f"no such master: {args.only}", file=sys.stderr)
            return 1
    if args.stills_only:
        specs = [s for s in specs if s.kind == "still"]

    out_dir = settings.masters_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    for spec in specs:
        t0 = time.time()
        label = f"{spec.id} ({spec.kind}, {spec.size[0]}x{spec.size[1]})"

        def progress(done: int, total: int, label: str = label) -> None:
            if done % 50 == 0 or done == total:
                print(f"\r  {label}: frame {done}/{total}", end="", flush=True)

        asset, sidecar = build_master(
            spec, out_dir, progress=progress if spec.kind == "video" else None
        )
        if spec.kind == "video":
            print()
        kb = asset.stat().st_size / 1024
        print(
            f"  {label}  ->  {asset.name} ({kb:,.0f} KB) + {sidecar.name}  [{time.time() - t0:.1f}s]"
        )

    print(f"\n{len(specs)} masters in {out_dir}  [{time.time() - started:.1f}s total]")
    print("All assets are SIMULATED and labelled as such in their sidecars.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
