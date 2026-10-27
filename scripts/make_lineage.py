"""Build a synthetic ad account so blast radius means something.

Why this exists. Blast radius answers "which other live ads are about to fail
for the same reason?" — and it is the moment the product stops being a detector
and becomes a fix. Derived from the benchmark runs alone it returned **zero**:
that data has one ad per master per enhancement, so nothing ever shares an
asset, and the most quotable claim in the demo resolved to nothing.

Real accounts do not look like that. One approved creative gets reused across
placements, audiences, regions and campaigns — which is exactly why a single
unwanted enhancement can contaminate dozens of live ads at once, and exactly
why fixing them one at a time is hopeless.

So this generates an ad population with that shape: each approved master is an
Asset, reused by several Ads, each enrolled in some enhancements and not others.
It is SIMULATED and labelled as such everywhere it surfaces. What it is NOT is a
fabricated result — the blast-radius query runs for real against it, and returns
whatever the data actually contains.

    python scripts/make_lineage.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.config import settings  # noqa: E402
from asapproved.synth.specs import MASTERS  # noqa: E402

SEED = 20261026

# Placements and audiences a single creative is realistically reused across.
PLACEMENTS = ["feed", "stories", "reels", "feed", "reels"]
AUDIENCES = [
    "broad-uk",
    "lookalike-1pc",
    "retargeting-site",
    "existing-customers",
    "age-25-34",
    "age-35-54",
    "london",
    "north-west",
]
CAMPAIGNS = ["always-on", "q4-push", "balance-transfer", "brand"]

FEATURES = [
    "image_touchups",
    "image_background_gen",
    "image_animation",
    "text_optimizations",
    "text_translation",
    "adapt_to_placement",
    "music_generation",
    "video_highlights",
    "translate_voiceover",
]


def main() -> int:
    rng = np.random.default_rng(SEED)
    ads: list[dict] = []

    for spec in MASTERS:
        asset_id = f"asset_{spec.id}"
        # A reused creative sits behind several ads. Spread is deliberate: some
        # assets are workhorses, some barely used, because a blast radius that
        # is always the same number looks staged.
        count = int(rng.integers(3, 9))
        for i in range(count):
            placement = PLACEMENTS[int(rng.integers(0, len(PLACEMENTS)))]
            if spec.kind == "still" and placement == "reels" and rng.random() < 0.5:
                placement = "feed"

            enrolments: dict[str, str] = {}
            for feature in FEATURES:
                video_only = {"music_generation", "video_highlights", "translate_voiceover"}
                if feature in video_only and spec.kind != "video":
                    continue
                # Most advertisers leave Advantage+ enhancements ON — that is the
                # whole premise of the problem this tool addresses.
                enrolments[feature] = "OPT_IN" if rng.random() < 0.62 else "OPT_OUT"

            ads.append(
                {
                    "ad_id": f"ad_{spec.id}_{i:02d}",
                    "name": f"{spec.brand.name} · {CAMPAIGNS[int(rng.integers(0, len(CAMPAIGNS)))]}"
                    f" · {AUDIENCES[int(rng.integers(0, len(AUDIENCES)))]}",
                    "master_id": spec.id,
                    "asset_id": asset_id,
                    "placement": placement,
                    "status": "ACTIVE",
                    "enrolments": enrolments,
                }
            )

    doc = {
        "source": "SIMULATED",
        "note": (
            "A synthetic ad account shaped like a real one: each approved master is "
            "an asset reused across several ads, each enrolled in some Advantage+ "
            "enhancements. Blast-radius queries run for real against this data."
        ),
        "seed": SEED,
        "assets": len({a["asset_id"] for a in ads}),
        "ads": len(ads),
        "features": FEATURES,
        "records": ads,
    }

    out = settings.data_dir / "lineage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    by_asset: dict[str, int] = {}
    for a in ads:
        by_asset[a["asset_id"]] = by_asset.get(a["asset_id"], 0) + 1

    print(f"{len(ads)} ads across {doc['assets']} assets -> {out}")
    print(f"  ads per asset: min {min(by_asset.values())}, max {max(by_asset.values())}")
    opt_in = sum(1 for a in ads for s in a["enrolments"].values() if s == "OPT_IN")
    total = sum(len(a["enrolments"]) for a in ads)
    print(f"  enhancement enrolments OPT_IN: {opt_in}/{total} ({opt_in / total * 100:.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
