"""Content-hash cache in front of every model call, plus the cost ledger.

Two jobs:

**Make the demo deterministic.** The key is a SHA-256 of (model, params, input
content hashes), so an identical call always replays from disk. In `demo` mode a
cache MISS raises instead of reaching the network — which is what makes "runs
from a clean clone with no API key" a mechanical fact rather than a hope, and
what stops a live demo from depending on latency, a rate limit, or a credit
balance.

**Make cost visible.** Every call appends a line to `costs.jsonl` with the model,
the tokens or frames, the computed cost and the latency. The README quotes cost
per variant from this file rather than from the pricing page, because the figure
that matters is the one we measured.

The cache is keyed on content, not on file paths, so re-rendering an identical
frame reuses the result and renaming a file does not.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from asapproved.canonical import canonical_bytes, sha256_bytes
from asapproved.config import settings

__all__ = [
    "CacheMiss",
    "cache_key",
    "get",
    "put",
    "cached_call",
    "log_cost",
    "read_costs",
    "CostSummary",
    "PRICING",
]


class CacheMiss(RuntimeError):
    """Raised when demo mode needs a result that was never recorded."""


# Verified 26 Oct 2026 against dev.meta.ai/docs/pricing-rate-limits (D-006).
# USD. Cached input is ~8x cheaper than fresh input, which is why the rulebook
# prefix is worth caching across the 48-variant benchmark.
PRICING: dict[str, dict[str, float]] = {
    "muse-spark-1.3": {
        "input_per_m": 1.25,
        "cached_input_per_m": 0.15,
        "output_per_m": 4.25,
    },
    "sam-3.1": {
        "per_1k_images": 2.50,
        "per_1k_video_frames": 0.20,
        "min_video_frames": 50,
    },
    "muse-voice-transcribe-1.0": {
        "per_hour": 0.18,
    },
}


def cache_key(model: str, params: dict[str, Any], input_hashes: list[str]) -> str:
    return sha256_bytes(
        canonical_bytes({"model": model, "params": params, "inputs": sorted(input_hashes)})
    )


def _path(key: str) -> Path:
    # Two-level fan-out: a flat directory of thousands of files is slow to list
    # and unpleasant to inspect by hand.
    return settings.cache_dir / key[:2] / f"{key}.json"


def get(key: str) -> Any | None:
    path = _path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["response"]
    except Exception:  # noqa: BLE001 - a corrupt entry is a miss, not a crash
        return None


def put(key: str, response: Any, meta: dict[str, Any] | None = None) -> Path:
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The key is deliberately not a field: it is the filename, so storing it
    # again carried no information, and a JSON object whose first field is
    # literally `"key": "<64 hex chars>"` trips every secret scanner there is.
    # gitleaks flagged all 17 recorded responses as generic-api-key leaks, and
    # the only ways past that are to delete the duplication or to allowlist a
    # path in the one check that is supposed to be unconditional.
    path.write_text(
        json.dumps(
            {
                "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "meta": meta or {},
                "response": response,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def drop(key: str) -> bool:
    """Remove one entry. True if something was there."""
    path = _path(key)
    if not path.exists():
        return False
    path.unlink()
    return True


def hash_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def cached_call(
    model: str,
    params: dict[str, Any],
    input_hashes: list[str],
    fn: Callable[[], Any],
    *,
    cost_fields: dict[str, Any] | Callable[[Any], dict[str, Any]] | None = None,
    validate: Callable[[Any], Any] | None = None,
) -> Any:
    """Return the cached response, else call `fn` — unless offline, where a miss raises.

    `cost_fields` may be a dict, for a price known before the call (SAM bills per
    image), or a callable applied to the response, for a price only the response
    knows. Token-metered models need the callable: the Spark path passed a fixed
    `{}` because the token counts do not exist until the reply arrives, so every
    structured call logged $0.00 and the ledger's total was zero by construction.

    `validate` is run against a response before it is stored, and again against a
    stored response before it is returned. It should raise on anything the caller
    cannot use. Without it, one malformed reply is written to disk and then
    replayed forever: a Spark call truncated by its token budget was cached, and
    every later run re-read the same half-written JSON and failed identically,
    with no network traffic to show why. A response that cannot be used is not a
    result worth keeping.
    """
    key = cache_key(model, params, input_hashes)
    hit = get(key)
    if hit is not None and validate is not None:
        try:
            validate(hit)
        except Exception:  # noqa: BLE001 - a poisoned entry is a miss, not a crash
            drop(key)
            hit = None
    if hit is not None:
        log_cost(model=model, key=key, cache_hit=True, cost_usd=0.0, seconds=0.0)
        return hit

    if settings.offline:
        raise CacheMiss(
            f"{model}: no cached response for this input and ASAPPROVED_MODE=demo. "
            "Demo mode never makes network calls. Set ASAPPROVED_MODE=live with a key "
            "to record it."
        )

    started = time.perf_counter()
    response = fn()
    elapsed = time.perf_counter() - started

    # Before `put`, so an unusable response never reaches the disk.
    if validate is not None:
        validate(response)

    fields = dict(cost_fields(response) if callable(cost_fields) else (cost_fields or {}))
    put(key, response, meta={"model": model, "params": params, **fields})
    log_cost(
        model=model,
        key=key,
        cache_hit=False,
        seconds=round(elapsed, 3),
        cost_usd=estimate_cost(model, fields),
        **fields,
    )
    return response


def estimate_cost(model: str, fields: dict[str, Any]) -> float:
    """Cost in USD from the published rates. Returns 0.0 for an unknown model."""
    price = PRICING.get(model)
    if not price:
        return 0.0

    if "input_per_m" in price:
        fresh = fields.get("input_tokens", 0) or 0
        cached = fields.get("cached_input_tokens", 0) or 0
        output = fields.get("output_tokens", 0) or 0
        return (
            fresh / 1e6 * price["input_per_m"]
            + cached / 1e6 * price["cached_input_per_m"]
            + output / 1e6 * price["output_per_m"]
        )

    if "per_1k_images" in price:
        images = fields.get("images", 0) or 0
        frames = fields.get("video_frames", 0) or 0
        if frames:
            # The 50-frame minimum is billed whether or not it is used.
            frames = max(frames, int(price["min_video_frames"]))
        return images / 1000 * price["per_1k_images"] + frames / 1000 * price["per_1k_video_frames"]

    if "per_hour" in price:
        return (fields.get("audio_seconds", 0) or 0) / 3600 * price["per_hour"]

    return 0.0


def log_cost(**fields: Any) -> None:
    path = settings.costs_log
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class CostSummary:
    calls: int
    cache_hits: int
    cost_usd: float
    seconds: float
    by_model: dict[str, float]

    @property
    def hit_rate(self) -> float:
        return self.cache_hits / self.calls if self.calls else 0.0


def read_costs(path: Path | None = None) -> CostSummary:
    target = Path(path or settings.costs_log)
    calls = hits = 0
    cost = seconds = 0.0
    by_model: dict[str, float] = {}
    if not target.exists():
        return CostSummary(0, 0, 0.0, 0.0, {})

    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        calls += 1
        hits += 1 if row.get("cache_hit") else 0
        c = float(row.get("cost_usd") or 0.0)
        cost += c
        seconds += float(row.get("seconds") or 0.0)
        model = row.get("model", "unknown")
        by_model[model] = by_model.get(model, 0.0) + c

    return CostSummary(calls, hits, round(cost, 6), round(seconds, 3), by_model)
