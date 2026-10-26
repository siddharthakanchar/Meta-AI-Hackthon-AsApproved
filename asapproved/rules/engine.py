"""C8 — the rules engine. Rules decide; the model only ever explains.

Three properties this file exists to guarantee:

1. **Deterministic.** Same context in, same findings out. No model call reaches
   this module. If a regulator asks why ad 14 was blocked, the answer is a
   function, a threshold and a frame reference.

2. **Nothing is asserted that was not measured.** Every input can be `None`,
   meaning "could not be established". A rule whose input is unknown returns
   `inconclusive` — never `pass` (which would wave through a real breach) and
   never `fail` (which would accuse an advertiser on a guess). This is the
   single most important behaviour in the engine and it is tested per rule.

3. **Thresholds are integers at comparison time.** The YAML carries
   human-readable values (0.02, 4.5) because a compliance officer may read it;
   the loader converts them into the fixed units the measurement engine emits
   (basis points, hundredths) so no float comparison decides a verdict.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from asapproved.text_norm import compare_prescribed, diff_summary

__all__ = [
    "Rulebook",
    "Rule",
    "Finding",
    "Context",
    "Status",
    "load_rulebook",
    "evaluate",
]

Status = Literal["fail", "pass", "inconclusive", "not_applicable"]

_RULEBOOK_PATH = Path(__file__).with_name("rulebook_uk_v1.yaml")

# How each rule's threshold is stored in YAML vs compared at runtime.
# Keeping this table in one place is what stops a 4.5 ever being compared
# against a 450.
_UNIT_SCALE: dict[str, int] = {
    "fraction_bp": 10_000,  # 0.02 -> 200 basis points
    "ratio_x100": 100,  # 4.5  -> 450
    "count": 1,
    "none": 1,
}

# R7 fires only when the warning is clearly smaller than body copy, not merely
# smaller by OCR rounding. 0.95 = a 5% shortfall before it counts.
R7_TOLERANCE = 0.95

# R1 needs a meaningful fraction AND a meaningful absolute area. Measured on
# VariantBench-UK: a benign re-encode moved 865 pixels of a thin one-line
# region (11.5% of it), while the smallest genuine seeded change moved
# 27,234. The floor sits in that gap, well clear of both.
R1_MIN_CHANGED_PIXELS = 2_500

_RULE_UNITS: dict[str, str] = {
    "R1": "fraction_bp",
    "R2": "none",
    "R3": "none",
    "R4": "fraction_bp",
    "R5": "none",
    "R6": "ratio_x100",
    "R7": "none",
    "R8": "none",
    "R9": "none",
    "R10": "none",
    "R11": "none",
    "R12": "count",
    "B1": "none",
}


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    citation: str
    paraphrase: str
    logic: str
    severity: str
    threshold: int | None
    threshold_display: str
    units: str
    inputs: list[str]
    sub_checks: list[str] = field(default_factory=list)
    benchmark_only: bool = False
    note: str = ""


@dataclass(frozen=True)
class Rulebook:
    version: str
    status: str
    jurisdiction: str
    sources_checked: str | None
    prescribed_texts: dict[str, str]
    rules: list[Rule]

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)

    @property
    def verified(self) -> bool:
        return self.status == "verified" and bool(self.sources_checked)


@dataclass(frozen=True)
class Finding:
    """One rule's verdict on one variant, with everything needed to defend it."""

    rule_id: str
    rulebook_version: str
    title: str
    citation: str
    paraphrase: str
    status: Status
    severity: str
    detail: str
    measured: int | None = None
    measured_display: str = ""
    threshold: int | None = None
    threshold_display: str = ""
    units: str = "none"
    evidence: dict[str, Any] = field(default_factory=dict)
    sub_results: dict[str, str] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    benchmark_only: bool = False
    not_legal_advice: bool = True

    @property
    def failed(self) -> bool:
        return self.status == "fail"

    @property
    def blocking(self) -> bool:
        return self.failed and self.severity == "block" and not self.benchmark_only

    def to_record(self) -> dict[str, Any]:
        """Chain-safe dict for the evidence log — integers and strings only."""
        return {
            "rule_id": self.rule_id,
            "rulebook_version": self.rulebook_version,
            "status": self.status,
            "severity": self.severity,
            "citation": self.citation,
            "detail": self.detail,
            "measured": self.measured,
            "measured_display": self.measured_display,
            "threshold": self.threshold,
            "threshold_display": self.threshold_display,
            "units": self.units,
            "evidence": self.evidence,
            "sub_results": self.sub_results,
            "caveats": self.caveats,
            "benchmark_only": self.benchmark_only,
            "not_legal_advice": self.not_legal_advice,
        }


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _scale_threshold(rule_id: str, raw: Any) -> tuple[int | None, str, str]:
    """Return (integer threshold, display string, units)."""
    units = _RULE_UNITS.get(rule_id, "none")
    if raw is None:
        return None, "—", units
    scale = _UNIT_SCALE[units]
    value = int(round(float(raw) * scale))
    if units == "fraction_bp":
        display = f"{float(raw) * 100:g}%"
    elif units == "ratio_x100":
        display = f"{float(raw):g}:1"
    else:
        display = f"{raw:g}" if isinstance(raw, (int, float)) else str(raw)
    return value, display, units


@lru_cache(maxsize=4)
def load_rulebook(path: str | None = None) -> Rulebook:
    raw = yaml.safe_load(Path(path or _RULEBOOK_PATH).read_text(encoding="utf-8"))
    rules: list[Rule] = []
    for item in raw["rules"]:
        threshold, display, units = _scale_threshold(item["id"], item.get("threshold"))
        rules.append(
            Rule(
                id=item["id"],
                title=item["title"],
                citation=item["citation"],
                paraphrase=" ".join(str(item["paraphrase"]).split()),
                logic=item["logic"],
                severity=item.get("severity", raw["defaults"]["severity"]),
                threshold=threshold,
                threshold_display=display,
                units=units,
                inputs=list(item.get("inputs") or []),
                sub_checks=list(item.get("sub_checks") or []),
                benchmark_only=bool(item.get("benchmark_only", False)),
                note=" ".join(str(item.get("note", "")).split()),
            )
        )
    return Rulebook(
        version=raw["version"],
        status=raw.get("status", "draft"),
        jurisdiction=raw.get("jurisdiction", "UK"),
        sources_checked=raw.get("sources_checked"),
        prescribed_texts={k: " ".join(v.split()) for k, v in raw["prescribed_texts"].items()},
        rules=rules,
    )


# ---------------------------------------------------------------------------
# the context a rule is evaluated against
# ---------------------------------------------------------------------------


@dataclass
class Context:
    """Everything the rules may look at. `None` always means "not established".

    Deliberately flat and explicit: a rule reaching into a nested pipeline object
    would make it impossible to say, in a test, exactly what a rule depends on.
    """

    variant_id: str = ""
    master_id: str = ""
    is_video: bool = False
    fps: int | None = None
    placement: str | None = None
    investment_type: str | None = None

    # Geometry trust gate: when alignment failed, R1/R3 must not fire (C3).
    alignment_ok: bool = True
    alignment_note: str = ""

    # Diff ∩ region, in basis points of the region's own area.
    changed_in_region_bp: dict[str, int] = field(default_factory=dict)
    changed_pixels_in_region: dict[str, int] = field(default_factory=dict)

    # Per-region measurements on master and variant.
    master_regions: dict[str, dict[str, Any]] = field(default_factory=dict)
    variant_regions: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Video visibility, basis points of frames.
    visible_ratio_bp: dict[str, int] = field(default_factory=dict)
    longest_gap_frames: dict[str, int] = field(default_factory=dict)

    # Placement occlusion, pixels.
    occluded_pixels: dict[str, int] = field(default_factory=dict)
    occlusion_caveats: list[str] = field(default_factory=list)

    # Text and claims.
    warning_text_variant: str | None = None
    # "ocr" | "model" | "exact" — decides how strictly R11 may compare. OCR
    # output is a READING of the creative, not the creative, so exact equality
    # would accuse advertisers of the engine's own misreadings.
    warning_text_source: str = "exact"
    cost_of_credit_present: bool | None = None
    representative_example_present: bool | None = None

    # Audio (R9). None = no transcript available.
    trigger_spoken: bool | None = None
    apr_spoken: bool | None = None

    # Settings drift (R2).
    manifest_settings: dict[str, str] = field(default_factory=dict)
    live_settings: dict[str, str] = field(default_factory=dict)

    # B1 benchmark input.
    warning_word_count: int | None = None
    warning_seconds_visible: float | None = None

    # Which labels count as the warning / APR in this creative.
    warning_label: str = "warning"
    apr_label: str = "apr"
    # Set by `evaluate` so findings record the book that actually ran.
    rulebook_version: str = ""
    prescribed_texts: dict[str, str] = field(default_factory=dict)

    def region(self, which: str, label: str) -> dict[str, Any] | None:
        source = self.master_regions if which == "master" else self.variant_regions
        return source.get(label)


# ---------------------------------------------------------------------------
# logic handlers
# ---------------------------------------------------------------------------

def _locate_failed(region: dict[str, Any] | None) -> bool:
    """True when a region is absent only because we could not look for it.

    A region we searched for and did not find is evidence. A region we could not
    search for is not. Collapsing both into `present: False` gave one flag four
    different confident readings: R3 accused the advertiser of removing the
    warning (severity: block), R5/R6/R7 called the real breach not-applicable,
    and R12 returned a pass. Reachable with no code change at all — OCR is an
    optional extra, and without it both locators collapse.
    """
    if region is None:
        return True
    if region.get("present"):
        return False
    return not region.get("locate_confident", True)


Handler = Callable[[Rule, Context], Finding]
_HANDLERS: dict[str, Handler] = {}


def handler(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _HANDLERS[name] = fn
        return fn

    return register


def _finding(
    rule: Rule,
    book_version: str,
    status: Status,
    detail: str,
    **kw: Any,
) -> Finding:
    fields: dict[str, Any] = {
        "rule_id": rule.id,
        "rulebook_version": book_version,
        "title": rule.title,
        "citation": rule.citation,
        "paraphrase": rule.paraphrase,
        "status": status,
        "severity": rule.severity,
        "detail": detail,
        "threshold": rule.threshold,
        "threshold_display": rule.threshold_display,
        "units": rule.units,
        "benchmark_only": rule.benchmark_only,
    }
    # Handlers may override the threshold, because not every rule compares
    # against a fixed rulebook value: R7 measures the warning against the ad's
    # own body copy and R8 the APR against its own trigger. The comparator is
    # part of the evidence in those cases, so it has to reach the finding.
    fields.update(kw)
    return Finding(**fields)


@handler("intersection_area_ratio")
def _r1(rule: Rule, ctx: Context) -> Finding:
    """R1 — a claim or warning region was materially changed."""
    if not ctx.alignment_ok:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "Variant could not be aligned to the master, so change inside a region "
            f"cannot be located. {ctx.alignment_note}".strip(),
            caveats=["alignment failed"],
        )

    watched = [label for label in (ctx.warning_label, ctx.apr_label, "trigger") if label]
    measured = {k: v for k, v in ctx.changed_in_region_bp.items() if k in watched}
    if not measured:
        return _finding(rule, ctx_version(ctx), "inconclusive", "No claim region was measured.")

    worst_label = max(measured, key=lambda k: measured[k])
    worst = measured[worst_label]
    assert rule.threshold is not None

    # A percentage of a very small region is mostly encoder noise: a thin
    # one-line "Capital at risk" strip measured 11.5% changed on a variant whose
    # only edit was re-encoding, purely because the denominator is small. Require
    # a meaningful absolute area as well as a meaningful fraction.
    changed_px = ctx.changed_pixels_in_region.get(worst_label)
    over_fraction = worst > rule.threshold
    below_noise_floor = changed_px is not None and changed_px < R1_MIN_CHANGED_PIXELS

    if over_fraction and below_noise_floor:
        # Over the rule's threshold as a fraction, but too small in absolute
        # terms for this detector to tell a real edit from encoder noise. That
        # is genuinely undecidable, so it is reported as such rather than
        # resolved in either party's favour.
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            f"{worst / 100:.1f}% of the '{worst_label}' region differs, but that is only "
            f"{changed_px:,} pixels — below the {R1_MIN_CHANGED_PIXELS:,}-pixel floor where "
            "this detector can separate a real edit from re-encoding artefacts.",
            measured=worst,
            measured_display=f"{worst / 100:.1f}%",
            caveats=["change too small to distinguish from compression noise"],
            evidence={"region": worst_label, "changed_pixels": changed_px},
        )

    failed = over_fraction
    return _finding(
        rule,
        ctx_version(ctx),
        "fail" if failed else "pass",
        (
            f"{worst / 100:.1f}% of the '{worst_label}' region changed from the approved master "
            f"(threshold {rule.threshold_display})."
            if failed
            else f"Largest change inside a claim region was {worst / 100:.1f}% "
            f"('{worst_label}'), within the {rule.threshold_display} threshold."
        ),
        measured=worst,
        measured_display=f"{worst / 100:.1f}%",
        evidence={"region": worst_label, "per_region_bp": measured},
    )


@handler("status_regression")
def _r2(rule: Rule, ctx: Context) -> Finding:
    """R2 — an enhancement is OPT_IN now that was OPT_OUT at approval."""
    if not ctx.manifest_settings:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "No enhancement settings were recorded at approval, so drift cannot be computed.",
            caveats=["no approval-time settings snapshot"],
        )
    if not ctx.live_settings:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "Live enhancement settings are unavailable (Marketing API not reachable).",
            caveats=["no live settings"],
        )

    drifted = sorted(
        feature
        for feature, live in ctx.live_settings.items()
        if live == "OPT_IN" and ctx.manifest_settings.get(feature) == "OPT_OUT"
    )
    if drifted:
        return _finding(
            rule,
            ctx_version(ctx),
            "fail",
            f"{len(drifted)} enhancement(s) switched on after approval: {', '.join(drifted)}.",
            measured=len(drifted),
            measured_display=str(len(drifted)),
            evidence={"drifted_features": drifted},
        )
    return _finding(
        rule, ctx_version(ctx), "pass", "Enhancement settings match the approval manifest."
    )


@handler("warning_not_fully_visible")
def _r3(rule: Rule, ctx: Context) -> Finding:
    """R3 — the warning was present on the master but is clipped or gone."""
    if not ctx.alignment_ok:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            f"Variant could not be aligned to the master. {ctx.alignment_note}".strip(),
            caveats=["alignment failed"],
        )

    master = ctx.region("master", ctx.warning_label)
    if not master or not master.get("present"):
        return _finding(
            rule,
            ctx_version(ctx),
            "not_applicable",
            "The approved master carries no warning region, so nothing can have been removed.",
        )

    variant = ctx.region("variant", ctx.warning_label)
    if _locate_failed(variant):
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "The warning could not be located in the variant. That is a failure to look, "
            "not evidence of removal.",
            caveats=["region could not be located"],
        )
    if not variant or not variant.get("present"):
        return _finding(
            rule,
            ctx_version(ctx),
            "fail",
            "The approved warning is absent from the delivered variant.",
            measured=0,
            measured_display="absent",
            evidence={"master_box": master.get("bbox")},
        )
    if variant.get("clipped"):
        # Touching the frame edge is a suspicion, not a finding. A warning
        # legitimately set flush to the edge trips it too, and the box may be a
        # PREDICTED rectangle rather than a measured one — which is how a
        # warning sitting 50px clear of the edge was reported as truncated.
        if master.get("clipped"):
            return _finding(
                rule,
                ctx_version(ctx),
                "pass",
                "The warning reaches the frame edge, as it does on the approved master.",
                evidence={"variant_box": variant.get("bbox")},
            )
        if variant.get("located_by") in {"alignment", "text"}:
            return _finding(
                rule,
                ctx_version(ctx),
                "inconclusive",
                "The warning appears to reach the frame edge, but its position was inferred "
                "rather than matched, so truncation cannot be asserted.",
                caveats=["position inferred, not matched"],
                evidence={"variant_box": variant.get("bbox")},
            )
        return _finding(
            rule,
            ctx_version(ctx),
            "fail",
            "The warning reaches the frame edge in the variant and may be truncated; "
            "it did not on the approved master.",
            measured=1,
            measured_display="clipped",
            evidence={"variant_box": variant.get("bbox")},
        )
    return _finding(
        rule, ctx_version(ctx), "pass", "The warning is present and fully within frame."
    )


@handler("ratio_below")
def _r4(rule: Rule, ctx: Context) -> Finding:
    """R4 — short-form video: the warning must be on screen throughout."""
    if not ctx.is_video:
        return _finding(
            rule, ctx_version(ctx), "not_applicable", "Not a video promotion."
        )
    ratio = ctx.visible_ratio_bp.get(ctx.warning_label)
    if ratio is None:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "Per-frame visibility of the warning was not measured.",
        )

    assert rule.threshold is not None
    gap = ctx.longest_gap_frames.get(ctx.warning_label)
    gap_note = ""
    if gap and ctx.fps:
        gap_note = f" Longest continuous absence: {gap / ctx.fps:.1f}s."

    failed = ratio < rule.threshold
    return _finding(
        rule,
        ctx_version(ctx),
        "fail" if failed else "pass",
        (
            f"The warning is on screen for {ratio / 100:.1f}% of frames, below the "
            f"{rule.threshold_display} the guidance expects.{gap_note}"
            if failed
            else f"The warning is on screen for {ratio / 100:.1f}% of frames.{gap_note}"
        ),
        measured=ratio,
        measured_display=f"{ratio / 100:.1f}%",
        evidence={"longest_gap_frames": gap, "fps": ctx.fps},
    )


@handler("presentation_checks")
def _r5(rule: Rule, ctx: Context) -> Finding:
    """R5 — own border AND bold AND underlined (COBS 4.12A.36R)."""
    variant = ctx.region("variant", ctx.warning_label)
    if _locate_failed(variant):
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "The warning could not be located, so this cannot be assessed.",
            caveats=["region could not be located"],
        )
    if not variant or not variant.get("present"):
        return _finding(
            rule,
            ctx_version(ctx),
            "not_applicable",
            "No warning region in the variant to assess.",
        )

    results: dict[str, str] = {}
    for check in rule.sub_checks or ["border"]:
        value = variant.get(f"{check}_present")
        if value is None:
            results[check] = "inconclusive"
        else:
            results[check] = "pass" if value else "fail"

    failing = [k for k, v in results.items() if v == "fail"]
    unknown = [k for k, v in results.items() if v == "inconclusive"]

    if failing:
        status: Status = "fail"
        detail = f"Warning presentation fails on: {', '.join(failing)}."
    elif unknown and len(unknown) == len(results):
        status = "inconclusive"
        detail = f"None of the presentation checks could be measured: {', '.join(unknown)}."
    elif unknown:
        # COBS 4.12A.36R is a conjunction: border AND bold AND underline. With
        # two limbs unmeasured, "pass" asserts compliance with a rule we checked
        # a third of — and contradicts this engine's own stated invariant that an
        # unknown input never yields a pass. Report what we know and no more.
        status = "inconclusive"
        detail = (
            f"Measured checks pass ({', '.join(k for k, v in results.items() if v == 'pass')}), "
            f"but {', '.join(unknown)} could not be measured, and the rule requires all of "
            "them."
        )
    else:
        status = "pass"
        detail = "Warning is bordered, bold and underlined."

    return _finding(
        rule,
        ctx_version(ctx),
        status,
        detail,
        sub_results=results,
        caveats=[f"{k} not measurable" for k in unknown],
        evidence={"variant_box": variant.get("bbox")},
    )


@handler("value_below")
def _r6(rule: Rule, ctx: Context) -> Finding:
    """R6 — warning contrast below the legibility threshold."""
    variant = ctx.region("variant", ctx.warning_label)
    if _locate_failed(variant):
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "The warning could not be located, so this cannot be assessed.",
            caveats=["region could not be located"],
        )
    if not variant or not variant.get("present"):
        return _finding(rule, ctx_version(ctx), "not_applicable", "No warning region to measure.")

    contrast = variant.get("contrast_x100")
    if contrast is None:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "Contrast could not be measured in the warning region (no usable "
            "foreground/background split).",
            caveats=["contrast not measurable"],
        )

    assert rule.threshold is not None
    failed = contrast < rule.threshold
    return _finding(
        rule,
        ctx_version(ctx),
        "fail" if failed else "pass",
        (
            f"Warning text contrast is {contrast / 100:.2f}:1, below the "
            f"{rule.threshold_display} design threshold."
            if failed
            else f"Warning text contrast is {contrast / 100:.2f}:1."
        ),
        measured=contrast,
        measured_display=f"{contrast / 100:.2f}:1",
        caveats=[
            "4.5:1 is an engineering proxy for legibility (WCAG AA), not a figure the FCA "
            "prescribes."
        ],
        evidence={"variant_box": variant.get("bbox")},
    )


@handler("height_below_median")
def _r7(rule: Rule, ctx: Context) -> Finding:
    """R7 — warning text smaller than the ad's body copy."""
    warning = ctx.region("variant", ctx.warning_label)
    body = ctx.region("variant", "body")
    if _locate_failed(warning):
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "The warning could not be located, so its size cannot be compared.",
            caveats=["region could not be located"],
        )
    if not warning or not warning.get("present"):
        return _finding(rule, ctx_version(ctx), "not_applicable", "No warning region to measure.")
    if not body or body.get("text_height") is None:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "No body copy was measured, so there is nothing to compare the warning against.",
            caveats=["no body-text baseline"],
        )

    w_height = warning.get("text_height")
    if w_height is None:
        return _finding(
            rule, ctx_version(ctx), "inconclusive", "Warning text height was not measured."
        )

    b_height = body["text_height"]
    # Tolerance, because these heights come from OCR glyph boxes, which include
    # ascenders and descenders and therefore track the characters present as much
    # as the type size. Two pixels between "24.9% APR" and "subject to status" is
    # the engine's noise floor, not a prominence breach — and blocking a
    # compliant ad over it would be exactly the false-positive behaviour that
    # makes compliance tooling get switched off.
    failed = w_height < int(b_height * R7_TOLERANCE)
    return _finding(
        rule,
        ctx_version(ctx),
        "fail" if failed else "pass",
        (
            f"Warning text is {w_height}px against body copy at {b_height}px — smaller than "
            "the surrounding copy."
            if failed
            else f"Warning text is {w_height}px against body copy at {b_height}px."
        ),
        measured=w_height,
        measured_display=f"{w_height}px",
        threshold=b_height,
        threshold_display=f"{b_height}px",
        evidence={"warning_px": w_height, "body_px": b_height},
    )


@handler("prominence_parity")
def _r8(rule: Rule, ctx: Context) -> Finding:
    """R8 — representative APR no less prominent than its trigger (CONC 3.5.7R)."""
    apr = ctx.region("variant", ctx.apr_label)
    trigger = ctx.region("variant", "trigger")
    if ctx.apr_label != "apr":
        return _finding(
            rule,
            ctx_version(ctx),
            "not_applicable",
            "Not a consumer-credit promotion, so no representative APR applies.",
        )
    if not trigger or not trigger.get("present"):
        return _finding(
            rule, ctx_version(ctx), "not_applicable", "No trigger feature present."
        )
    if not apr or not apr.get("present"):
        return _finding(
            rule,
            ctx_version(ctx),
            "fail",
            "The trigger is shown but the representative APR is absent.",
            measured=0,
            measured_display="absent",
        )

    reasons: list[str] = []
    # Text height only. Falling back to the bounding-box height compared the
    # CONTAINER rather than the type, so an APR whose type size had been halved
    # inside an unchanged box passed as "at least as prominent", and two
    # unmeasured heights compared 0px against 0px and passed as well.
    apr_h = apr.get("text_height")
    trg_h = trigger.get("text_height")
    size_known = isinstance(apr_h, int) and isinstance(trg_h, int) and apr_h > 0 and trg_h > 0
    if size_known and apr_h < trg_h:
        reasons.append(f"APR text is {apr_h}px against the trigger's {trg_h}px")

    if ctx.is_video:
        apr_vis = ctx.visible_ratio_bp.get(ctx.apr_label)
        trg_vis = ctx.visible_ratio_bp.get("trigger")
        if apr_vis is not None and trg_vis is not None and apr_vis < trg_vis:
            reasons.append(
                f"APR is on screen for {apr_vis / 100:.1f}% of frames against the trigger's "
                f"{trg_vis / 100:.1f}%"
            )

    time_known = ctx.is_video and (
        ctx.visible_ratio_bp.get(ctx.apr_label) is not None
        and ctx.visible_ratio_bp.get("trigger") is not None
    )
    if not reasons and not size_known and not time_known:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "Neither the APR's type size nor its time on screen could be measured, so "
            "prominence cannot be compared.",
            caveats=["no measurable prominence signal"],
        )

    if reasons:
        return _finding(
            rule,
            ctx_version(ctx),
            "fail",
            "The representative APR is less prominent than its trigger: " + "; ".join(reasons) + ".",
            measured=apr_h,
            measured_display=f"{apr_h}px",
            threshold=trg_h,
            threshold_display=f"{trg_h}px",
            evidence={
                "apr_height_px": apr_h,
                "trigger_height_px": trg_h,
                "apr_visible_bp": ctx.visible_ratio_bp.get(ctx.apr_label),
                "trigger_visible_bp": ctx.visible_ratio_bp.get("trigger"),
            },
        )
    detail = "Representative APR is at least as prominent as its trigger"
    if size_known:
        detail += f" ({apr_h}px vs {trg_h}px)"
    return _finding(
        rule,
        ctx_version(ctx),
        "pass",
        detail + ".",
        measured=apr_h if size_known else None,
        measured_display=f"{apr_h}px" if size_known else "",
        threshold=trg_h if size_known else None,
        threshold_display=f"{trg_h}px" if size_known else "",
    )


@handler("spoken_parity")
def _r9(rule: Rule, ctx: Context) -> Finding:
    """R9 — trigger spoken but representative APR not spoken."""
    if not ctx.is_video:
        return _finding(rule, ctx_version(ctx), "not_applicable", "Not a video promotion.")
    if ctx.trigger_spoken is None or ctx.apr_spoken is None:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "No transcript is available, so spoken parity cannot be assessed.",
            caveats=["no audio transcript"],
        )
    if not ctx.trigger_spoken:
        return _finding(
            rule,
            ctx_version(ctx),
            "not_applicable",
            "The trigger is not spoken, so spoken parity does not arise.",
        )
    if not ctx.apr_spoken:
        return _finding(
            rule,
            ctx_version(ctx),
            "fail",
            "The trigger is spoken in the voiceover but the representative APR is not.",
            measured=0,
            measured_display="APR not spoken",
        )
    return _finding(
        rule, ctx_version(ctx), "pass", "Both the trigger and the representative APR are spoken."
    )


@handler("example_missing")
def _r10(rule: Rule, ctx: Context) -> Finding:
    """R10 — a cost-of-credit figure with no representative example."""
    if ctx.apr_label != "apr":
        return _finding(
            rule, ctx_version(ctx), "not_applicable", "Not a consumer-credit promotion."
        )
    if ctx.cost_of_credit_present is None or ctx.representative_example_present is None:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "Claim extraction did not establish whether a cost-of-credit figure or a "
            "representative example is present.",
            caveats=["claims not extracted"],
        )
    if not ctx.cost_of_credit_present:
        return _finding(
            rule, ctx_version(ctx), "not_applicable", "No cost-of-credit figure is shown."
        )
    if not ctx.representative_example_present:
        return _finding(
            rule,
            ctx_version(ctx),
            "fail",
            "A cost-of-credit figure is shown without a representative example.",
            measured=0,
            measured_display="example absent",
        )
    return _finding(
        rule, ctx_version(ctx), "pass", "A representative example accompanies the cost figures."
    )


@handler("prescribed_text_mismatch")
def _r11(rule: Rule, ctx: Context) -> Finding:
    """R11 — the prescribed wording was altered (COBS 4.12A.11R)."""
    if not ctx.investment_type:
        return _finding(
            rule,
            ctx_version(ctx),
            "not_applicable",
            "Not a high-risk investment promotion, so no prescribed wording applies.",
        )
    # From the book that ran, not the shipped one: a pinned rulebook's own
    # prescribed wording must be what R11 compares against.
    prescribed = (ctx.prescribed_texts or load_rulebook().prescribed_texts).get(
        ctx.investment_type
    )
    if prescribed is None:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            f"No prescribed wording is on file for investment type "
            f"'{ctx.investment_type}'.",
            caveats=["unknown investment type"],
        )
    if ctx.warning_text_variant is None:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "The warning text could not be read from the variant.",
            caveats=["warning text not extracted"],
        )

    verdict, ratio = compare_prescribed(
        ctx.warning_text_variant, prescribed, source=ctx.warning_text_source
    )
    evidence = {
        "investment_type": ctx.investment_type,
        "observed": ctx.warning_text_variant,
        "prescribed": prescribed,
        "similarity_pct": int(round(ratio * 100)),
        "text_source": ctx.warning_text_source,
    }
    ocr_caveat = (
        [
            "Warning text was read by OCR, which mis-renders characters and spacing; "
            "comparison uses a calibrated similarity band, not exact equality."
        ]
        if ctx.warning_text_source == "ocr"
        else []
    )

    if verdict == "match":
        return _finding(
            rule,
            ctx_version(ctx),
            "pass",
            "The warning matches the prescribed wording for this investment type "
            f"({int(round(ratio * 100))}% similarity).",
            evidence=evidence,
            caveats=ocr_caveat,
        )
    if verdict == "uncertain":
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            f"The warning is {int(round(ratio * 100))}% similar to the prescribed wording — "
            "too close to call between an OCR misreading and a genuine edit.",
            evidence=evidence,
            caveats=ocr_caveat + ["similarity falls in the undecidable band"],
        )
    return _finding(
        rule,
        ctx_version(ctx),
        "fail",
        "The prescribed warning wording has been altered: "
        + diff_summary(ctx.warning_text_variant, prescribed),
        measured=int(round(ratio * 100)),
        measured_display=f"{int(round(ratio * 100))}% similar",
        evidence=evidence,
        caveats=ocr_caveat,
    )


@handler("occlusion_pixels_above")
def _r12(rule: Rule, ctx: Context) -> Finding:
    """R12 — warning or APR inside the platform's UI overlay zone."""
    if not ctx.placement:
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "No placement is known for this ad, so overlay zones cannot be applied.",
            caveats=["placement unknown"],
        )
    watched = [label for label in (ctx.warning_label, ctx.apr_label) if label]
    present = [
        label
        for label in watched
        if (ctx.region("variant", label) or {}).get("present")
        or not _locate_failed(ctx.region("variant", label))
    ]
    measured = {k: v for k, v in ctx.occluded_pixels.items() if k in watched}
    unmeasured = [label for label in present if label not in measured]

    if not measured:
        return _finding(
            rule, ctx_version(ctx), "inconclusive", "Occlusion was not measured."
        )
    if unmeasured:
        # Do not announce "no part of the warning or APR falls inside the zone"
        # while one of them was never measured. A pass that names regions it did
        # not look at is the kind of confident silence this engine exists to
        # avoid.
        return _finding(
            rule,
            ctx_version(ctx),
            "inconclusive",
            "Occlusion could not be measured for: " + ", ".join(sorted(unmeasured)) + ".",
            caveats=["region not measured for occlusion"],
            evidence={"placement": ctx.placement, "per_region_px": measured},
        )

    assert rule.threshold is not None
    worst_label = max(measured, key=lambda k: measured[k])
    worst = measured[worst_label]
    failed = worst > rule.threshold
    return _finding(
        rule,
        ctx_version(ctx),
        "fail" if failed else "pass",
        (
            f"{worst:,} pixels of the '{worst_label}' fall inside the {ctx.placement} "
            "interface overlay zone, where platform chrome can obscure them."
            if failed
            else f"No part of the warning or APR falls inside the {ctx.placement} overlay zone."
        ),
        measured=worst,
        measured_display=f"{worst:,}px",
        caveats=list(ctx.occlusion_caveats),
        evidence={"placement": ctx.placement, "per_region_px": measured},
    )


@handler("hold_time_shortfall")
def _b1(rule: Rule, ctx: Context) -> Finding:
    """B1 — Clearcast TV hold time. A TV convention, never the online legal test."""
    if not ctx.is_video:
        return _finding(rule, ctx_version(ctx), "not_applicable", "Not a video promotion.")
    if ctx.warning_word_count is None or ctx.warning_seconds_visible is None:
        return _finding(
            rule, ctx_version(ctx), "inconclusive", "Word count or on-screen time not measured."
        )

    words = ctx.warning_word_count
    required = 0.2 * words + 2.0 + (3.0 if words >= 10 else 0.0)
    shortfall = required - ctx.warning_seconds_visible
    failed = shortfall > 0
    return _finding(
        rule,
        ctx_version(ctx),
        "fail" if failed else "pass",
        (
            f"TV benchmark only: {words} words would need {required:.1f}s on screen under "
            f"Clearcast's calculator; measured {ctx.warning_seconds_visible:.1f}s."
            if failed
            else f"TV benchmark only: {ctx.warning_seconds_visible:.1f}s on screen meets the "
            f"{required:.1f}s Clearcast allowance for {words} words."
        ),
        measured=int(round(ctx.warning_seconds_visible * 100)),
        measured_display=f"{ctx.warning_seconds_visible:.1f}s",
        threshold=int(round(required * 100)),
        threshold_display=f"{required:.1f}s",
        caveats=["UK TV clearance convention, not the legal test for online promotions"],
    )


def ctx_version(ctx: Context) -> str:
    """The rulebook version that actually decided, not the default one.

    `evaluate(ctx, rulebook=...)` ran the caller's book while every finding was
    stamped `uk_v1`, so a firm pinning its own thresholds would get a signed
    evidence record naming the wrong rulebook for the numbers that decided.
    """
    return ctx.rulebook_version or load_rulebook().version


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------


def evaluate(ctx: Context, rulebook: Rulebook | None = None) -> list[Finding]:
    """Run every rule against the context. Order follows the rulebook."""
    book = rulebook or load_rulebook()
    ctx.rulebook_version = book.version
    if not ctx.prescribed_texts:
        ctx.prescribed_texts = book.prescribed_texts
    findings: list[Finding] = []
    for rule in book.rules:
        fn = _HANDLERS.get(rule.logic)
        if fn is None:
            findings.append(
                _finding(
                    rule,
                    book.version,
                    "inconclusive",
                    f"No handler implemented for logic '{rule.logic}'.",
                    caveats=["unimplemented rule logic"],
                )
            )
            continue
        findings.append(fn(rule, ctx))
    return findings


def summarise(findings: list[Finding]) -> dict[str, Any]:
    """Counts the UI and the evidence record both need."""
    return {
        "fail": sum(1 for f in findings if f.status == "fail" and not f.benchmark_only),
        "blocking": sum(1 for f in findings if f.blocking),
        "pass": sum(1 for f in findings if f.status == "pass"),
        "inconclusive": sum(1 for f in findings if f.status == "inconclusive"),
        "not_applicable": sum(1 for f in findings if f.status == "not_applicable"),
        "failed_rules": [f.rule_id for f in findings if f.status == "fail" and not f.benchmark_only],
        "inconclusive_rules": [f.rule_id for f in findings if f.status == "inconclusive"],
    }
