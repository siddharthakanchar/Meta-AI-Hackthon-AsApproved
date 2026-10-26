"""C10 — Muse Spark writes the compliance note; a validator keeps it honest.

The validator rejects any number, quoted string or rule ID in the note that does
not appear in the evidence bundle. Rejections are retried once, then fall back to
a deterministic template. This is the "rules decide, LLM explains" boundary — the
note never changes a verdict.
"""

from __future__ import annotations

__all__ = ["write_note", "validate_note", "template_note"]


def write_note(evidence: dict) -> str:
    raise NotImplementedError("Phase 5")


def validate_note(note: str, evidence: dict):  # noqa: ANN201
    """Return (ok, violations). Phase 5."""
    raise NotImplementedError("Phase 5")


def template_note(evidence: dict) -> str:
    raise NotImplementedError("Phase 5")
