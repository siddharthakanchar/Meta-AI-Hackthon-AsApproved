"""D5 — scoring VariantBench-UK.

Baselines:
  B0  Muse Spark alone — master + variant + rulebook in one prompt. Needs an API
      key; reported as "not run" until one exists, never as a zero.
  B1  Pixel diff alone — flag when enough of any claim region changed. The
      straw man that a lot of "AI compliance" tooling actually is.
  B2  AsApproved — align, track, measure, rules.

Two decisions that shape every number here:

**Inconclusive is not a pass.** When a rule cannot be assessed (no transcript,
no settings snapshot, OCR unavailable) the variant is excluded from that rule's
denominator and counted separately. Folding "don't know" into "no violation"
would inflate precision exactly where the tool is weakest, which is the one
place a compliance buyer will look.

**The false-block rate is reported as prominently as recall.** A tool that
blocks good ads gets switched off in a week, so the benign half of the set is
not a footnote.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from asapproved.pipeline import check_variant, load_master
from asapproved.vision.diff import changed_in_region, diff_pair

__all__ = [
    "Prediction",
    "RuleScore",
    "BaselineReport",
    "run_b1",
    "run_b2",
    "score",
    "write_report",
    "load_labels",
]

# Rules with no pixel expression at all; never counted against a vision baseline.
NON_PIXEL_RULES = {"R2"}


def load_labels(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass
class Prediction:
    variant_id: str
    predicted_rules: list[str] = field(default_factory=list)
    inconclusive_rules: list[str] = field(default_factory=list)
    blocked: bool = False
    seconds: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class RuleScore:
    rule_id: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    not_evaluated: int = 0

    @property
    def precision(self) -> float | None:
        denom = self.tp + self.fp
        return (self.tp / denom) if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.tp + self.fn
        return (self.tp / denom) if denom else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)


@dataclass
class BaselineReport:
    name: str
    description: str
    variants_scored: int = 0
    variants_skipped: int = 0
    # Variant-level: did we flag a violating variant at all?
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0
    per_rule: dict[str, RuleScore] = field(default_factory=dict)
    mean_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        d = self.tp + self.fp
        return (self.tp / d) if d else None

    @property
    def recall(self) -> float | None:
        d = self.tp + self.fn
        return (self.tp / d) if d else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)

    @property
    def false_block_rate(self) -> float | None:
        """Share of BENIGN variants wrongly flagged. The number buyers care about."""
        d = self.fp + self.tn
        return (self.fp / d) if d else None


# ---------------------------------------------------------------------------
# baselines
# ---------------------------------------------------------------------------


def run_b1(labels: dict, masters_dir: Path, variants_dir: Path, *, threshold_bp: int = 200) -> list[Prediction]:
    """Pixel diff alone: flag if any claim region changed more than the threshold.

    No alignment trust gate, no measurement, no rules — deliberately. This is the
    comparison that shows whether the rest of the pipeline earns its complexity.
    """
    from asapproved.pipeline import sample_frames

    preds: list[Prediction] = []
    for label in labels["labels"]:
        vp = variants_dir / label["file"]
        if not vp.exists():
            preds.append(Prediction(label["variant_id"], error="variant not built"))
            continue
        t0 = time.time()
        try:
            master = load_master(label["master_id"], masters_dir)
            mframes, _, _ = sample_frames(master.path)
            vframes, _, _ = sample_frames(vp)
            diff = diff_pair(mframes[0], vframes[0])

            import numpy as np

            flagged = False
            for region_label, box in master.regions.items():
                if region_label not in {"warning", "apr", "risk_note", "trigger"}:
                    continue
                mask = np.zeros(mframes[0].shape[:2], dtype=bool)
                x, y, w, h = box
                mask[max(0, y) : y + h, max(0, x) : x + w] = True
                if changed_in_region(diff, mask, region_label).fraction_bp > threshold_bp:
                    flagged = True
                    break
            preds.append(
                Prediction(
                    label["variant_id"],
                    predicted_rules=["R1"] if flagged else [],
                    blocked=flagged,
                    seconds=time.time() - t0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            preds.append(Prediction(label["variant_id"], error=f"{type(exc).__name__}: {exc}"))
    return preds


def run_b2(labels: dict, masters_dir: Path, variants_dir: Path, *, limit: int | None = None) -> list[Prediction]:
    """The full AsApproved pipeline."""
    preds: list[Prediction] = []
    items = labels["labels"][:limit] if limit else labels["labels"]
    for label in items:
        vp = variants_dir / label["file"]
        if not vp.exists():
            preds.append(Prediction(label["variant_id"], error="variant not built"))
            continue
        t0 = time.time()
        try:
            master = load_master(label["master_id"], masters_dir)
            result = check_variant(vp, master)
            preds.append(
                Prediction(
                    variant_id=label["variant_id"],
                    predicted_rules=sorted(result.summary["failed_rules"]),
                    inconclusive_rules=sorted(result.summary["inconclusive_rules"]),
                    blocked=bool(result.summary["fail"]),
                    seconds=time.time() - t0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            preds.append(Prediction(label["variant_id"], error=f"{type(exc).__name__}: {exc}"))
    return preds


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def score(
    name: str,
    description: str,
    predictions: list[Prediction],
    labels: dict,
    *,
    rule_aware: bool = True,
) -> BaselineReport:
    by_id = {lab["variant_id"]: lab for lab in labels["labels"]}
    report = BaselineReport(name=name, description=description)
    total_seconds = 0.0

    all_rules = sorted(
        {r for lab in labels["labels"] for r in lab["violated_rules"]} - NON_PIXEL_RULES
    )
    report.per_rule = {r: RuleScore(r) for r in all_rules}

    for pred in predictions:
        truth = by_id.get(pred.variant_id)
        if truth is None:
            continue
        if not pred.ok:
            report.variants_skipped += 1
            report.errors.append(f"{pred.variant_id}: {pred.error}")
            continue

        # Audio-only variants cannot be judged without a transcript. Excluded
        # from scoring and reported, never silently counted as passes.
        if truth.get("requires_audio"):
            report.variants_skipped += 1
            report.notes.append(f"{pred.variant_id}: requires audio, not evaluated")
            continue

        report.variants_scored += 1
        total_seconds += pred.seconds

        truth_rules = set(truth["violated_rules"]) - NON_PIXEL_RULES
        is_violation = bool(truth_rules)

        if is_violation and pred.blocked:
            report.tp += 1
        elif is_violation and not pred.blocked:
            report.fn += 1
        elif not is_violation and pred.blocked:
            report.fp += 1
        else:
            report.tn += 1

        if not rule_aware:
            continue

        predicted = set(pred.predicted_rules)
        unknown = set(pred.inconclusive_rules)
        for rule_id, rs in report.per_rule.items():
            expected = rule_id in truth_rules
            got = rule_id in predicted
            if expected and rule_id in unknown and not got:
                # Could not be assessed: out of this rule's denominator.
                rs.not_evaluated += 1
                continue
            if expected and got:
                rs.tp += 1
            elif expected and not got:
                rs.fn += 1
            elif not expected and got:
                rs.fp += 1

    report.mean_seconds = total_seconds / report.variants_scored if report.variants_scored else 0.0
    return report


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def write_report(reports: list[BaselineReport], out_path: Path, labels: dict) -> Path:
    lines: list[str] = [
        "# VariantBench-UK results",
        "",
        f"Dataset: {labels['count']} variants "
        f"({labels['violations']} seeded violations, {labels['benign']} benign) "
        f"from 12 approved masters.",
        f"Labels frozen at `{labels.get('labels_sha256', 'unset')[:16]}…`.",
        "",
        "All creative is SIMULATED. Numbers are reported as measured, including "
        "where a baseline beats the full pipeline.",
        "",
        "## Variant-level detection",
        "",
        "| Baseline | Precision | Recall | F1 | False-block rate | Scored | Not evaluated | Mean s/variant |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        lines.append(
            f"| **{r.name}** — {r.description} | {_pct(r.precision)} | {_pct(r.recall)} | "
            f"{_pct(r.f1)} | {_pct(r.false_block_rate)} | {r.variants_scored} | "
            f"{r.variants_skipped} | {r.mean_seconds:.1f} |"
        )

    lines += [
        "",
        "**False-block rate** is the share of benign variants wrongly flagged. A tool that "
        "blocks compliant ads gets switched off, so it is reported beside recall rather than "
        "below it.",
        "",
        "### Reading this table honestly",
        "",
        "A pixel diff scores close to the full pipeline on *variant-level detection*, and "
        "that is a real result, not a flaw in the baseline. The question it answers — "
        "\"did something change?\" — is the easy one, and almost any edit to a claim region "
        "trips it.",
        "",
        "It is also not the question a compliance officer can act on. They need to know "
        "**which rule broke, by how much, against which threshold, and with which frame as "
        "evidence** — because that is what goes in the record and what a regulator asks "
        "about. The per-rule table below is where the two separate: B1 can only ever "
        "assert R1, so every other rule is a miss it cannot even attempt.",
        "",
        "## Per-rule attribution",
        "",
    ]
    for r in reports:
        if not any(rs.tp + rs.fp + rs.fn + rs.not_evaluated for rs in r.per_rule.values()):
            continue
        lines += [
            f"### {r.name}",
            "",
            "| Rule | TP | FP | FN | Precision | Recall | F1 | Not evaluated |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for rule_id, rs in sorted(r.per_rule.items(), key=lambda kv: int(kv[0][1:])):
            lines.append(
                f"| {rule_id} | {rs.tp} | {rs.fp} | {rs.fn} | {_pct(rs.precision)} | "
                f"{_pct(rs.recall)} | {_pct(rs.f1)} | {rs.not_evaluated} |"
            )
        lines.append("")
        if r.notes:
            lines += ["Not evaluated:", ""] + [f"- {n}" for n in r.notes] + [""]
        if r.errors:
            lines += ["Errors:", ""] + [f"- {e}" for e in r.errors] + [""]

    lines += [
        "## Honesty notes",
        "",
        "- **Inconclusive is never counted as a pass.** Where a rule could not be assessed "
        "(no transcript, no settings snapshot, OCR unavailable) the variant leaves that "
        "rule's denominator and is counted in *Not evaluated*.",
        "- **R2 (settings drift) is excluded** from every vision baseline: it compares live "
        "API settings against the approval manifest and has no pixel expression.",
        "- Thresholds (2% region change, 4.5:1 contrast, 98% visibility) are engineering "
        "choices stated in the rulebook, not figures the FCA prescribes.",
        "- Region tracking in this run is normalised cross-correlation, not SAM 3.1. The "
        "comparison between the two is the point of §10's region-IoU metric.",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def report_to_dict(report: BaselineReport) -> dict[str, Any]:
    data = asdict(report)
    data["per_rule"] = {
        k: {
            **asdict(v),
            "precision": v.precision,
            "recall": v.recall,
            "f1": v.f1,
        }
        for k, v in report.per_rule.items()
    }
    data.update(
        {
            "precision": report.precision,
            "recall": report.recall,
            "f1": report.f1,
            "false_block_rate": report.false_block_rate,
        }
    )
    return data
