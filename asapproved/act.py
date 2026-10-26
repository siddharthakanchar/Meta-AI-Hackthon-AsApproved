"""D3 — Act, then Prove.

Act turns a Block decision into an opt-out across every affected sibling ad.
Prove re-reads the result and refuses to close the finding until it is confirmed.

**The default is a dry run, and that is a feature.** Without `ads_management`
write access the tool prints the exact payloads it would send, labelled as a dry
run everywhere it appears. A compliance tool that silently did nothing while
appearing to act would be far worse than one that is clear about what it cannot
do — and "here is the exact API call we would make" is itself the reviewable
artefact a regulator would want.

**Prove is not optional.** A finding does not close because a request returned
200. It closes when the settings read back as OPT_OUT *and* a freshly rendered
preview matches the approved master within tolerance. Acting and verifying are
different claims, and conflating them is how remediation becomes theatre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "OptOutPayload",
    "ActPlan",
    "ActResult",
    "ProveResult",
    "plan_opt_out",
    "apply_opt_out",
    "prove",
]


@dataclass(frozen=True)
class OptOutPayload:
    ad_id: str
    feature: str

    def body(self) -> dict[str, Any]:
        """The Marketing API body. Shape is VERIFY-pending until Phase 1 (V5/V7)."""
        return {
            "degrees_of_freedom_spec": {
                "creative_features_spec": {self.feature: {"enroll_status": "OPT_OUT"}}
            }
        }

    def request(self, api_version: str = "") -> dict[str, Any]:
        version = f"/{api_version}" if api_version else ""
        return {
            "method": "POST",
            "url": f"https://graph.facebook.com{version}/{self.ad_id}",
            "body": self.body(),
        }


@dataclass(frozen=True)
class ActPlan:
    feature: str
    asset_id: str
    payloads: list[OptOutPayload]
    reason: str
    approver: str

    @property
    def count(self) -> int:
        return len(self.payloads)

    def as_requests(self, api_version: str = "") -> list[dict[str, Any]]:
        return [p.request(api_version) for p in self.payloads]


@dataclass(frozen=True)
class ActResult:
    plan: ActPlan
    dry_run: bool
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return "DRY RUN — no changes were made" if self.dry_run else "applied"

    @property
    def ok(self) -> bool:
        return not self.failed


@dataclass(frozen=True)
class ProveResult:
    """Did the fix actually land? Settings AND rendering, not one or the other."""

    ad_id: str
    settings_opted_out: bool | None
    preview_matches_master: bool | None
    note: str = ""

    @property
    def proven(self) -> bool:
        return self.settings_opted_out is True and self.preview_matches_master is True

    @property
    def status(self) -> str:
        if self.proven:
            return "Closed – proven"
        if self.settings_opted_out is None or self.preview_matches_master is None:
            return "Open – could not verify"
        return "Open – fix not confirmed"


def plan_opt_out(
    ad_ids: list[str],
    feature: str,
    *,
    asset_id: str = "",
    reason: str = "",
    approver: str = "",
) -> ActPlan:
    """Build the payloads. Pure — safe to show in a dry run and to unit-test."""
    if not feature:
        raise ValueError("an opt-out needs a feature to opt out of")
    return ActPlan(
        feature=feature,
        asset_id=asset_id,
        payloads=[OptOutPayload(ad_id=ad, feature=feature) for ad in sorted(set(ad_ids))],
        reason=reason,
        approver=approver,
    )


def apply_opt_out(plan: ActPlan, *, dry_run: bool = True, client=None) -> ActResult:
    """Apply the plan, or report exactly what would be sent.

    `dry_run` defaults to True: acting on someone's live ad account is not
    something to do by omission.
    """
    if dry_run or client is None:
        return ActResult(plan=plan, dry_run=True, succeeded=[p.ad_id for p in plan.payloads])

    succeeded: list[str] = []
    failed: dict[str, str] = {}
    for payload in plan.payloads:
        try:
            client.update_ad_creative(payload.ad_id, payload.body())
            succeeded.append(payload.ad_id)
        except Exception as exc:  # noqa: BLE001 - per-ad failure must not abort the batch
            failed[payload.ad_id] = f"{type(exc).__name__}: {exc}"
    return ActResult(plan=plan, dry_run=False, succeeded=succeeded, failed=failed)


def prove(
    ad_ids: list[str],
    feature: str,
    *,
    client=None,
    recheck=None,
) -> list[ProveResult]:
    """Verify each ad twice: settings read back, and the preview re-checked.

    With no client, every result is `could not verify` — never `proven`. A tool
    that reports success it did not observe is worse than one that reports
    nothing.
    """
    results: list[ProveResult] = []
    for ad_id in sorted(set(ad_ids)):
        if client is None:
            results.append(
                ProveResult(
                    ad_id=ad_id,
                    settings_opted_out=None,
                    preview_matches_master=None,
                    note="No Marketing API access: cannot confirm the fix landed.",
                )
            )
            continue

        try:
            settings_ok = client.enroll_status(ad_id, feature) == "OPT_OUT"
        except Exception as exc:  # noqa: BLE001
            results.append(
                ProveResult(ad_id, None, None, note=f"settings read failed: {exc}")
            )
            continue

        preview_ok: bool | None = None
        note = ""
        if recheck is not None:
            try:
                preview_ok = bool(recheck(ad_id))
            except Exception as exc:  # noqa: BLE001
                note = f"re-check failed: {exc}"
        else:
            note = "No re-render available: settings confirmed, rendering not verified."

        results.append(ProveResult(ad_id, settings_ok, preview_ok, note=note))
    return results
