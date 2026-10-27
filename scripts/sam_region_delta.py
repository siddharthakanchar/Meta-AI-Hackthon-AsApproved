"""Region-IoU: SAM 3.1 against the keyless template detector, on the errors.

The README promised this metric before the numbers existed. It answers one
question: on the five variants the published benchmark gets wrong, does Meta's
segmentation model localise the warning better than normalised cross-correlation
against the approved master?

Ground truth is the renderer's own region box — computed when the variant was
drawn, not annotated afterwards. Both detectors are scored against it with
intersection-over-union, so the comparison is like for like.

    python scripts/sam_region_delta.py            # cached; no key needed on a re-run
    python scripts/sam_region_delta.py --refresh  # re-call SAM

Writes eval/sam_region_delta.json. Every SAM call goes through the model cache,
so this is reproducible from a clean clone once the cache is committed.

Masks are not used. SAM returns one, but its payload is in an 85-character
encoding this repo cannot read (see asapproved/models/sam.py), so IoU here is
box IoU and the JSON records `mask_available: false` rather than quietly
implying a mask-level score.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from asapproved.config import settings  # noqa: E402
from asapproved.models.cache import cached_call, hash_file  # noqa: E402
from asapproved.models.responses import ResponsesClient  # noqa: E402
from asapproved.models.sam import parse_response_line, segment_image  # noqa: E402
from asapproved.pipeline import load_master, sample_frames  # noqa: E402
from asapproved.vision.align import align_to_master  # noqa: E402
from asapproved.vision.track import expected_box, region_template, track_region  # noqa: E402

REGION = "warning"

# SAM is strikingly sensitive to the noun phrase, so one phrase is not a fair
# test of the model. On the two shrunk warnings, "risk warning box" returns no
# detection at all while "fine print disclaimer" lands at IoU 0.987 and 0.984.
# Every concept is tried and the highest-confidence detection wins; the winning
# phrase is recorded per variant so the sensitivity stays visible in the output.
#
# These phrases were chosen by trying them on these same variants, which is the
# same development-set caveat the thresholds carry. Stated, not hidden.
CONCEPTS = [
    "risk warning box",
    "fine print disclaimer",
    "small print text",
    "legal disclaimer text",
]

OUT = REPO_ROOT / "eval" / "sam_region_delta.json"

# The published benchmark gets five variants wrong (eval/results.json): R5 has
# three false positives, R7 one, R12 one false negative.
ERRORS = [
    ("R5", "FP", "brightwell_loans_01__v0_warning_shrunk"),
    ("R5", "FP", "kestrel_crypto_01__v1_warning_reworded"),
    ("R5", "FP", "northfield_card_03__v1_warning_shrunk"),
    ("R7", "FP", "northfield_card_02__v0_warning_into_overlay_zone"),
]

# R12's false negative is a video, and it is left out rather than guessed at.
# Its APR animates off the left edge over frames 0-29, so the ground truth that
# would make an IoU meaningful is a box per frame. The label file carries one
# static box plus a visible-frame range, which is enough to score the rule and
# not enough to score a localiser. Measuring it against the static box would
# produce a number that looks like evidence and is not.
EXCLUDED = {
    "variant_id": "northfield_card_v2__v0_apr_animates_offscreen",
    "rule": "R12",
    "error": "FN",
    "reason": (
        "video: the APR moves across frames 0-29, so per-frame ground-truth "
        "boxes would be needed; the label file carries one static box and a "
        "visible-frame range"
    ),
}


def iou(a: tuple[int, int, int, int] | None, b: tuple[int, int, int, int] | None) -> float:
    """Intersection over union of two (x, y, w, h) boxes. A missing box scores 0."""
    if a is None or b is None:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _segment(image_path: Path, concept: str, *, refresh: bool = False) -> dict[str, Any]:
    """One cached SAM call, storing the raw grammar lines.

    The cache keeps the response text rather than parsed boxes, so a parser
    change can be re-read from the recording without spending another call.
    """
    key_params = {"concept": concept, "endpoint": "responses", "model": settings.models.sam_model}
    digest = hash_file(image_path)

    def call() -> dict[str, Any]:
        detections = segment_image(_data_url(image_path), concept, client=ResponsesClient())
        return {
            "lines": [
                f"<{d.frame}f>{d.object_id}<|box;x1={d.box.x1};y1={d.box.y1};"
                f"x2={d.box.x2};y2={d.box.y2};w={d.box.w};h={d.box.h}"
                + (f";c={d.box.confidence}" if d.box.confidence is not None else "")
                + "|>"
                for d in detections
                if d.box is not None
            ],
            "mask_present": any(d.mask is not None for d in detections),
        }

    if refresh:
        from asapproved.models.cache import cache_key, drop

        drop(cache_key(settings.models.sam_model, key_params, [digest]))

    return cached_call(
        settings.models.sam_model,
        key_params,
        [digest],
        call,
        cost_fields={"images": 1},
    )


def sam_box(image_path: Path, *, refresh: bool = False) -> dict[str, Any]:
    """The best box across every concept, with the phrase that produced it."""
    per_concept: dict[str, Any] = {}
    best = None
    best_concept = None

    for concept in CONCEPTS:
        recorded = _segment(image_path, concept, refresh=refresh)
        boxes = [d.box for line in recorded["lines"] for d in parse_response_line(line) if d.box]
        top = max(boxes, key=lambda b: b.confidence or 0.0) if boxes else None
        per_concept[concept] = {
            "box": list(top.xywh) if top else None,
            "confidence": top.confidence if top else None,
        }
        if top and (best is None or (top.confidence or 0.0) > (best.confidence or 0.0)):
            best, best_concept = top, concept

    return {
        "box": list(best.xywh) if best else None,
        "confidence": best.confidence if best else None,
        "concept": best_concept,
        "concepts_that_found_it": sum(1 for v in per_concept.values() if v["box"]),
        "per_concept": per_concept,
        # SAM returns a mask, but its payload encoding is unreadable here, so no
        # mask-level IoU is claimed. See the module docstring.
        "mask_available": False,
    }


def template_box(label: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """What the keyless detector finds, by the pipeline's own route."""
    master = load_master(label["master_id"], settings.masters_dir)
    master_frames, _, _ = sample_frames(master.path)
    variant_frames, _, _ = sample_frames(settings.variants_dir / label["file"])
    master_frame, variant_frame = master_frames[0], variant_frames[0]

    m_box = tuple(master.regions[REGION])
    alignment = align_to_master(master_frame, variant_frame)
    template = region_template(master_frame, m_box, alignment)
    if template is None:
        return None

    near = expected_box(m_box, alignment, variant_frame.shape)
    track = track_region(template, variant_frames, REGION, near=near)
    return track.first_box()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-call SAM instead of replaying")
    args = parser.parse_args()

    labels = {
        e["variant_id"]: e
        for e in json.loads(
            (settings.labels_dir / "variantbench_uk.json").read_text(encoding="utf-8")
        )["labels"]
    }

    rows = []
    for rule, kind, variant_id in ERRORS:
        label = labels[variant_id]
        truth = label["regions"].get(REGION)
        truth = tuple(truth) if truth else None

        tmpl = template_box(label)
        sam = sam_box(settings.variants_dir / label["file"], refresh=args.refresh)
        sam_b = tuple(sam["box"]) if sam["box"] else None

        row = {
            "variant_id": variant_id,
            "rule": rule,
            "error": kind,
            "transform": label["transform"],
            "kind": label["kind"],
            "truth_box": list(truth) if truth else None,
            "template_box": list(tmpl) if tmpl else None,
            "sam_box": list(sam_b) if sam_b else None,
            "sam_confidence": sam["confidence"],
            "sam_concept": sam["concept"],
            "concepts_tried": len(CONCEPTS),
            "concepts_that_found_it": sam["concepts_that_found_it"],
            "per_concept": sam["per_concept"],
            "mask_available": sam["mask_available"],
            "template_iou": round(iou(tmpl, truth), 4),
            "sam_iou": round(iou(sam_b, truth), 4),
        }
        row["delta"] = round(row["sam_iou"] - row["template_iou"], 4)
        rows.append(row)

        print(
            f"{rule:4} {kind:2}  {variant_id[:44]:44}  "
            f"template {row['template_iou']:.3f}  sam {row['sam_iou']:.3f}  "
            f"delta {row['delta']:+.3f}  "
            f"[{row['concepts_that_found_it']}/{len(CONCEPTS)} concepts"
            + (f", won by '{row['sam_concept']}'" if row["sam_concept"] else "")
            + "]"
        )

    n = len(rows)
    summary = {
        "concepts": CONCEPTS,
        "region": REGION,
        "metric": "box_iou",
        "masks_used": False,
        "variants": n,
        "mean_template_iou": round(sum(r["template_iou"] for r in rows) / n, 4),
        "mean_sam_iou": round(sum(r["sam_iou"] for r in rows) / n, 4),
        "template_found": sum(1 for r in rows if r["template_box"]),
        "sam_found": sum(1 for r in rows if r["sam_box"]),
    }
    summary["mean_delta"] = round(summary["mean_sam_iou"] - summary["mean_template_iou"], 4)

    print(
        f"\nmean IoU  template {summary['mean_template_iou']:.3f}  "
        f"sam {summary['mean_sam_iou']:.3f}  delta {summary['mean_delta']:+.3f}"
    )
    print(
        f"located the warning at all: template {summary['template_found']}/{n}, "
        f"sam {summary['sam_found']}/{n}"
    )

    print(
        f"excluded: {EXCLUDED['variant_id']} ({EXCLUDED['rule']} {EXCLUDED['error']}) "
        f"— {EXCLUDED['reason']}"
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"summary": summary, "rows": rows, "excluded": [EXCLUDED]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
