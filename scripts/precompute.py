"""Precompute every variant check into data/runs/ so the demo needs no keys.

    python scripts/precompute.py [--limit N] [--only <variant_id>]

This is what makes the §13 quality gate true rather than aspirational: a clean
clone with no API key and no network runs the hero case from cache in under two
seconds. It also means the live demo cannot be derailed by latency, a rate limit
or an exhausted credit — the three things most likely to go wrong on stage.

Writes per variant:
  data/runs/<variant_id>.json          findings, measurements, provenance
  data/runs/previews/<variant_id>_*.jpg  master, variant, heat map, overlays
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.components.render import draw_overlay_zone, draw_region, heatmap_overlay  # noqa: E402
from asapproved.config import settings  # noqa: E402
from asapproved.explain import template_note  # noqa: E402
from asapproved.pipeline import check_variant, load_master, sample_frames  # noqa: E402

PREVIEW_MAX_W = 520
JPEG_Q = 82


def _save(img: np.ndarray, path: Path) -> str:
    h, w = img.shape[:2]
    if w > PREVIEW_MAX_W:
        scale = PREVIEW_MAX_W / w
        img = cv2.resize(img, (PREVIEW_MAX_W, int(h * scale)), interpolation=cv2.INTER_AREA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_Q])
    return path.name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", default=None)
    args = parser.parse_args()

    labels_path = settings.labels_dir / "variantbench_uk.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    items = labels["labels"]
    if args.only:
        items = [lab for lab in items if lab["variant_id"] == args.only]
    if args.limit:
        items = items[: args.limit]

    runs_dir = settings.data_dir / "runs"
    previews = runs_dir / "previews"
    runs_dir.mkdir(parents=True, exist_ok=True)

    index: list[dict] = []
    started = time.time()

    for i, lab in enumerate(items, start=1):
        vp = settings.variants_dir / lab["file"]
        if not vp.exists():
            print(f"  [skip] {lab['variant_id']} not built")
            continue

        t0 = time.time()
        master = load_master(lab["master_id"], settings.masters_dir)
        result = check_variant(vp, master)

        mframes, _, _ = sample_frames(master.path)
        vframes, src_fps, stride = sample_frames(vp)
        mframe, vframe = mframes[0], vframes[0]

        stem = lab["variant_id"]
        files = {
            "master": _save(mframe, previews / f"{stem}_master.jpg"),
            "variant": _save(vframe, previews / f"{stem}_variant.jpg"),
        }

        if result.diff is not None:
            files["heat"] = _save(
                heatmap_overlay(mframe, result.diff.ssim_map), previews / f"{stem}_heat.jpg"
            )

        annotated = vframe.copy()
        if master.placement:
            key = "reels_with_disclaimer" if master.placement == "reels" else master.placement
            annotated = draw_overlay_zone(annotated, key)
        for label, track in result.tracks.items():
            box = track.first_box()
            if box is None:
                continue
            status_colour = "#e5484d" if label in ("warning", "apr") else "#f5a524"
            annotated = draw_region(annotated, box, label, status_colour)
        files["annotated"] = _save(annotated, previews / f"{stem}_annotated.jpg")

        visibility = {label: track.visible for label, track in result.tracks.items()}

        record = result.to_record()
        record.update(
            {
                "label": {
                    "benign": lab["benign"],
                    "transform": lab["transform"],
                    "enhancement": lab["enhancement"],
                    "description": lab["description"],
                    "violated_rules": lab["violated_rules"],
                    "requires_audio": lab["requires_audio"],
                },
                "master": {
                    "id": master.id,
                    "placement": master.placement,
                    "investment_type": master.investment_type,
                    "kind": master.sidecar.get("kind"),
                    "regions": master.regions,
                },
                "previews": files,
                "visibility": visibility,
                "sample_fps": (src_fps / stride) if src_fps else 0.0,
                "note": template_note(result.findings),
                "seconds": round(time.time() - t0, 2),
            }
        )
        (runs_dir / f"{stem}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        index.append(
            {
                "variant_id": stem,
                "master_id": master.id,
                "benign": lab["benign"],
                "transform": lab["transform"],
                "enhancement": lab["enhancement"],
                "kind": master.sidecar.get("kind"),
                "placement": master.placement,
                "fail": record["summary"]["fail"],
                "blocking": record["summary"]["blocking"],
                "inconclusive": record["summary"]["inconclusive"],
                "failed_rules": record["summary"]["failed_rules"],
                "expected_rules": lab["violated_rules"],
                "seconds": record["seconds"],
            }
        )
        flag = "BENIGN " if lab["benign"] else "VIOLATE"
        print(
            f"  [{flag}] {stem}: {record['summary']['fail']} fail "
            f"({','.join(record['summary']['failed_rules']) or '-'}) "
            f"[{record['seconds']:.1f}s]  {i}/{len(items)}"
        )

    if not index:
        print(
            f"\nNothing was cached — no variants found in {settings.variants_dir}.\n"
            "data/runs/index.json left untouched.\n\n"
            "Build the dataset first:\n"
            "  python scripts/make_masters.py\n"
            "  python scripts/make_variants.py",
            file=sys.stderr,
        )
        return 1

    if args.limit or args.only:
        # A partial run must not replace the full index. Overwriting it with a
        # subset silently shrank the demo; overwriting it with nothing killed it
        # outright, and the app then showed an empty selectbox rather than
        # saying why.
        existing = runs_dir / "index.json"
        if existing.exists():
            previous = json.loads(existing.read_text(encoding="utf-8")).get("runs", [])
            keep = {row["variant_id"] for row in index}
            index = [row for row in previous if row["variant_id"] not in keep] + index
            index.sort(key=lambda row: row["variant_id"])
            print(f"  merged into the existing index ({len(index)} runs total)")

    (runs_dir / "index.json").write_text(
        json.dumps(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "labels_sha256": labels.get("labels_sha256"),
                "count": len(index),
                "runs": index,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n{len(index)} runs cached in {runs_dir}  [{time.time() - started:.0f}s]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
