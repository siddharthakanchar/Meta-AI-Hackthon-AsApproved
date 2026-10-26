"""Evaluate the rulebook against one variant's measurements and extractions.

Pure and deterministic: same inputs -> same findings. One unit test per rule
(Phase 5).
"""

from __future__ import annotations

__all__ = ["load_rulebook", "Finding", "evaluate"]


class Finding:  # noqa: D101 - Phase 5
    pass


def load_rulebook(path=None):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 5")


def evaluate(rulebook, context: dict) -> list:  # noqa: ANN001
    raise NotImplementedError("Phase 5")
