"""C10 — the compliance note, and the validator that keeps it honest.

The boundary this file defends: **rules decide, the model explains.** A language
model writing about regulation will, given the chance, produce a fluent sentence
containing a number nobody measured, a rule nobody ran, or a quotation from a
handbook it is reconstructing from memory. In a compliance tool that is not a
cosmetic flaw — it is a fabricated audit trail.

So every generated note is parsed before it is shown, and rejected if it contains:

  - a number that is not in the evidence (any figure, percentage, duration,
    pixel count or ratio must appear in a finding),
  - a rule ID that did not fire,
  - a quoted string that is not in the evidence,
  - a regulation citation that is not in the rulebook.

A rejected note is retried once, then replaced by a deterministic template built
from the same findings. The template is always correct and merely duller, which
is the right direction to fail in. `validate_note` is pure and has no model
dependency, so it is unit-tested against adversarial text rather than against
whatever a model happened to say that day.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from asapproved.rules.engine import Finding

__all__ = [
    "NoteResult",
    "Validation",
    "validate_note",
    "template_note",
    "write_note",
    "evidence_bundle",
]

# Numbers that carry no claim: ordinals, small counts in prose, years.
_NUMBER_RE = re.compile(r"(?<![\w/])(\d+(?:[.,]\d+)*)\s*(%|px|s\b|:1)?")
_RULE_RE = re.compile(r"\b([RB]\d{1,2})\b")
# Straight apostrophes are possessives in English prose ("the trigger's 34px"),
# not quotation marks. Treating them as delimiters made the validator reject its
# own template note for "quoting" the text between two possessives.
_QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{8,})[\"“”]")


@dataclass(frozen=True)
class Validation:
    ok: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class NoteResult:
    text: str
    source: str  # "model" | "template" | "model_after_retry"
    validation: Validation
    attempts: int = 1

    @property
    def is_template(self) -> bool:
        return self.source == "template"


def evidence_bundle(findings: list[Finding], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything a note is allowed to refer to, flattened for checking."""
    numbers: set[str] = set()
    quotes: set[str] = set()
    citations: set[str] = set()
    rule_ids: set[str] = set()

    for f in findings:
        rule_ids.add(f.rule_id)
        citations.add(f.citation)
        for value in (f.measured_display, f.threshold_display):
            if value:
                for m in _NUMBER_RE.finditer(value):
                    numbers.add(_canon_number(m.group(1)))
        for value in (f.measured, f.threshold):
            if value is not None:
                numbers.add(_canon_number(str(value)))
        # Human units come from the finding's own display strings rather than from
        # arithmetic on raw values. Deriving them blindly (every integer divided by
        # 100) admitted "0.4" because a bounding box started at x=40 — which is how
        # "the APR appears for 0.4 seconds" passed as evidence-backed.
        for value in (f.evidence or {}).values():
            _collect(value, numbers, quotes)
        if f.detail:
            for m in _NUMBER_RE.finditer(f.detail):
                numbers.add(_canon_number(m.group(1)))

    for value in (extra or {}).values():
        _collect(value, numbers, quotes)

    return {
        "numbers": numbers,
        "quotes": quotes,
        "citations": citations,
        "rule_ids": rule_ids,
    }


def _collect(value: Any, numbers: set[str], quotes: set[str]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        numbers.add(_canon_number(str(value)))
        return
    if isinstance(value, str):
        quotes.add(value.strip().casefold())
        for m in _NUMBER_RE.finditer(value):
            numbers.add(_canon_number(m.group(1)))
        return
    if isinstance(value, dict):
        for k, v in value.items():
            quotes.add(str(k).strip().casefold())
            _collect(v, numbers, quotes)
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _collect(v, numbers, quotes)


def _canon_number(raw: str) -> str:
    """Normalise so 8, 8.0 and 08 compare equal."""
    text = raw.replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return text
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def validate_note(
    note: str,
    findings: list[Finding],
    *,
    extra_evidence: dict[str, Any] | None = None,
    allowed_prose_numbers: set[str] | None = None,
) -> Validation:
    """Reject anything the evidence does not support."""
    bundle = evidence_bundle(findings, extra_evidence)
    violations: list[str] = []

    # Small integers that appear in ordinary prose ("two rules fired") are
    # allowed when they match a count the findings actually support.
    allowed = set(allowed_prose_numbers or set())
    allowed.update(
        {
            str(len([f for f in findings if f.status == "fail"])),
            str(len([f for f in findings if f.status == "inconclusive"])),
        }
    )

    for m in _RULE_RE.finditer(note):
        rule_id = m.group(1)
        if rule_id not in bundle["rule_ids"]:
            violations.append(f"cites rule {rule_id}, which was not evaluated")

    # Citations carry digits (COBS 4.12A, CONC 3.5.7R, FG24/1 para 1.5). They are
    # validated as citations below; mining them for "figures" made the validator
    # reject every correctly-cited note it produced.
    scannable = _CITATION_RE.sub(" ", note)

    for m in _NUMBER_RE.finditer(scannable):
        token = _canon_number(m.group(1))
        if token in bundle["numbers"] or token in allowed:
            continue
        violations.append(f"states the figure {m.group(0).strip()!r}, which is not in the evidence")

    for m in _QUOTE_RE.finditer(note):
        quoted = m.group(1).strip().casefold()
        if not any(quoted in known for known in bundle["quotes"]):
            violations.append(f"quotes {m.group(1)[:48]!r}, which is not in the evidence")

    # A citation must come from a rule that was actually evaluated.
    for citation in _find_citations(note):
        if not any(citation.casefold() in c.casefold() for c in bundle["citations"]):
            violations.append(f"cites {citation!r}, which is not in the rulebook for this check")

    return Validation(ok=not violations, violations=violations)


_CITATION_RE = re.compile(
    r"\b(?:COBS|CONC|FG|PRIN|SYSC)\s?[\w./]*\d[\w./]*"
    # ...including any paragraph or table reference that belongs to it. Without
    # this, "FG24/1 para 1.5" left a stray "1.5" behind, which the number check
    # then reported as an unsupported figure — in the engine's own template note.
    r"(?:\s+(?:para|paragraph|paras|table|annex)\s*[\w.]+)?",
    re.IGNORECASE,
)


def _find_citations(note: str) -> list[str]:
    return [m.group(0).strip() for m in _CITATION_RE.finditer(note)]


def template_note(findings: list[Finding], context_note: str = "") -> str:
    """Deterministic fallback. Always correct, never elegant."""
    failed = [f for f in findings if f.status == "fail" and not f.benchmark_only]
    unknown = [f for f in findings if f.status == "inconclusive"]

    if not failed:
        lines = ["No rule in rulebook " + findings[0].rulebook_version + " failed for this variant."]
    else:
        lines = [
            f"{len(failed)} rule(s) failed for this variant against rulebook "
            f"{failed[0].rulebook_version}."
        ]
        for f in failed:
            lines.append(f"- {f.rule_id} ({f.citation}): {f.detail}")
            for caveat in f.caveats:
                lines.append(f"  Caveat: {caveat}")

    if unknown:
        lines.append(
            f"{len(unknown)} rule(s) could not be assessed: "
            + ", ".join(f.rule_id for f in unknown)
            + ". These are reported as inconclusive and are not treated as passes."
        )

    if context_note:
        lines.append(context_note)

    lines.append(
        "Findings flag items for compliance review against paraphrased regulation. "
        "Not legal advice."
    )
    return "\n".join(lines)


def write_note(
    findings: list[Finding],
    *,
    model_fn=None,
    extra_evidence: dict[str, Any] | None = None,
    context_note: str = "",
) -> NoteResult:
    """Produce a compliance note: model if it passes validation, template otherwise.

    `model_fn(prompt) -> str` is injected rather than imported so this module
    stays keyless and unit-testable. Phase 4 passes the Spark client.
    """
    if model_fn is None:
        text = template_note(findings, context_note)
        return NoteResult(text=text, source="template", validation=Validation(True), attempts=0)

    prompt = build_prompt(findings, context_note)
    attempts = 0
    last: Validation | None = None

    for attempt in range(2):
        attempts += 1
        try:
            candidate = model_fn(prompt if attempt == 0 else _retry_prompt(prompt, last))
        except Exception:  # noqa: BLE001 - a model failure falls back, never breaks the check
            break
        validation = validate_note(candidate, findings, extra_evidence=extra_evidence)
        if validation.ok:
            return NoteResult(
                text=candidate,
                source="model" if attempt == 0 else "model_after_retry",
                validation=validation,
                attempts=attempts,
            )
        last = validation

    return NoteResult(
        text=template_note(findings, context_note),
        source="template",
        # `last if last is not None`, never `last or ...`: Validation.__bool__ is
        # self.ok, so a FAILED validation is falsy and `or` would silently throw
        # away exactly the violations the caller needs to see.
        validation=last if last is not None else Validation(True),
        attempts=attempts,
    )


def build_prompt(findings: list[Finding], context_note: str = "") -> str:
    lines = [
        "You are writing a short compliance note for a financial-promotions reviewer.",
        "",
        "Hard constraints:",
        "- Use ONLY the measurements, rule IDs and citations listed below.",
        "- Do not introduce any number that is not listed.",
        "- Do not quote any regulation text; cite by reference only.",
        "- Do not state a conclusion the findings do not state.",
        "- Three sentences maximum. Plain English.",
        "",
        "Findings:",
    ]
    for f in findings:
        if f.status in {"fail", "inconclusive"}:
            lines.append(
                f"- {f.rule_id} [{f.status}] ({f.citation}): {f.detail} "
                f"measured={f.measured_display or 'n/a'} threshold={f.threshold_display or 'n/a'}"
            )
    if context_note:
        lines += ["", f"Context: {context_note}"]
    return "\n".join(lines)


def _retry_prompt(prompt: str, validation: Validation | None) -> str:
    if validation is None:
        return prompt
    return (
        prompt
        + "\n\nYour previous answer was rejected for: "
        + "; ".join(validation.violations)
        + "\nRewrite using only the listed evidence."
    )
