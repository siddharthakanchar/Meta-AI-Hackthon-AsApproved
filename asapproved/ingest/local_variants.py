"""Load SIMULATED variants from local folders.

Anything loaded through here is labelled SIMULATED in the UI, the dataset and the
README. It is never presented as a real Meta-served variant (§0 rule 6).
"""

from __future__ import annotations

__all__ = ["load_variant_set"]


def load_variant_set(root):  # noqa: ANN001, ANN201
    raise NotImplementedError("Phase 3")
