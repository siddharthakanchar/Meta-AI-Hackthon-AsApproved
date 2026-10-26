"""D3 — Act, then Prove.

Act: on Block, set the enhancement to OPT_OUT on every affected sibling ad via
the Marketing API. If creative specs turn out to be immutable after creation
(playbook §8 item 3, VERIFY), Act instead creates a new creative with OPT_OUT and
repoints the ad, or pauses the ad.

Without write access, Act runs as a DRY RUN that prints the exact payloads it
would send — clearly labelled as such in the UI, the log and the README.

Prove: re-read settings (expect OPT_OUT on all N) and re-render the preview,
comparing it to the master within tolerance. Only then does the finding become
"Closed - proven".
"""

from __future__ import annotations

__all__ = ["plan_opt_out", "apply_opt_out", "prove"]


def plan_opt_out(ad_ids: list[str], feature: str) -> list[dict]:
    """Build the payloads. Pure function, safe to show in a dry run. Phase 6."""
    raise NotImplementedError("Phase 6")


def apply_opt_out(payloads: list[dict], dry_run: bool = True):  # noqa: ANN201
    raise NotImplementedError("Phase 6")


def prove(ad_ids: list[str], feature: str, master_hash: str):  # noqa: ANN201
    raise NotImplementedError("Phase 6")
