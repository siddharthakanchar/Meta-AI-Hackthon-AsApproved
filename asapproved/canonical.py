"""Canonical bytes for hashing and signing.

Everything AsApproved signs or hash-chains goes through here first. Two records
that mean the same thing must serialise to the same bytes, or a signature check
fails for a reason that has nothing to do with tampering — and on a tool whose
whole claim is tamper evidence, a false alarm is as damaging as a miss.

Rules:
- keys sorted, no insignificant whitespace;
- UTF-8, not ASCII escapes, so the FCA's curly apostrophe in "Don't invest"
  survives a round trip byte-for-byte;
- no NaN or Infinity (they are not valid JSON and do not round-trip);
- floats are rejected outright in signed payloads — see `assert_no_floats`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

__all__ = [
    "canonical_bytes",
    "canonical_json",
    "sha256_bytes",
    "sha256_file",
    "sha256_obj",
    "assert_no_floats",
]

_CHUNK = 1024 * 1024


def assert_no_floats(obj: Any, _path: str = "$") -> None:
    """Reject floats anywhere in a payload destined to be signed or chained.

    A measurement like 1.2000000000000002 seconds serialises differently across
    platforms and Python versions, which would break verification on a machine
    that is not the one that signed. Measurements are therefore carried as
    integers in fixed units (milliseconds, basis points, pixels) or as strings.
    This is a deliberate constraint on `measure.py`, enforced here rather than
    trusted to reviewers.
    """
    if isinstance(obj, float):
        raise TypeError(
            f"float at {_path}: signed payloads must use integers in fixed units "
            "(ms, basis points, pixels) or strings — floats do not round-trip reliably"
        )
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_floats(v, f"{_path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_no_floats(v, f"{_path}[{i}]")


def canonical_json(obj: Any) -> str:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_obj(obj: Any) -> str:
    return sha256_bytes(canonical_bytes(obj))


def sha256_file(path: str | Path) -> str:
    """Stream a file through SHA-256 — masters and variants are video-sized."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()
