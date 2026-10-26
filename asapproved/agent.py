"""D6 — the agentic compliance reviewer.

Muse Spark runs as a tool-calling agent over the evidence graph: answers "why was
ad 14 blocked?", drafts the re-approval request, lists which siblings changed.

Hard rule: every tool is read-only except `propose_decision`, which only ever
queues a proposal for human approval. The agent cannot block, accept or write to
the Marketing API.
"""

from __future__ import annotations

__all__ = ["TOOLS", "ask"]

TOOLS: list[dict] = []  # Phase 6


def ask(question: str, session_id: str | None = None) -> str:
    raise NotImplementedError("Phase 6")
