"""Content-hash cache in front of every model call, plus the cost ledger.

Key = SHA-256 of (model, params, input content hashes). Responses are stored on
disk so the demo, the tests and the benchmark replay byte-identically with no
API key present.

Also appends one line per call to costs.jsonl: model, tokens or frames, computed
cost, latency. The UI shows cost per variant from this (playbook §7).
"""

from __future__ import annotations

__all__ = ["cache_key", "get", "put", "cached_call", "log_cost"]


def cache_key(model: str, params: dict, input_hashes: list[str]) -> str:
    raise NotImplementedError("Phase 1")


def get(key: str):  # noqa: ANN201
    raise NotImplementedError("Phase 1")


def put(key: str, response) -> None:  # noqa: ANN001
    raise NotImplementedError("Phase 1")


def cached_call(model: str, params: dict, input_hashes: list[str], fn):  # noqa: ANN001, ANN201
    """Return the cached response, else call `fn` — unless offline, where a miss raises."""
    raise NotImplementedError("Phase 1")


def log_cost(**fields) -> None:  # noqa: ANN003
    raise NotImplementedError("Phase 1")
