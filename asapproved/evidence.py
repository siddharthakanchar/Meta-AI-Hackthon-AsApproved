"""C12 — append-only, hash-chained evidence log.

One JSON object per line. Each entry hashes the entry before it, so altering any
byte of record k invalidates k and every record after it. That is the property
the demo shows live: change one character, run `asapproved verify-log`, watch it
name the exact record that broke.

What this does and does not prove, stated plainly because a compliance tool that
overclaims is worse than one that claims nothing:
  - It proves the log has not been edited or reordered since it was written,
    including fields ADDED to a record: unknown top-level keys are rejected
    rather than ignored, so a line cannot be annotated and still verify.
  - It does NOT prove when it was written, and it does not stop someone who
    controls the file from rewriting the whole chain from record k onward. That
    needs either a signature per record or an external anchor (a timestamping authority, or shipping the head hash off-box).
    A firm deploying this would anchor the head daily. Said so in the README.

Retention framing: COBS 4.11.1R — 3 years by default, 5 for MiFID business.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asapproved.canonical import assert_no_floats, canonical_bytes, sha256_bytes

__all__ = [
    "GENESIS_PREV",
    "LogEntry",
    "ChainResult",
    "append_record",
    "read_entries",
    "verify_chain",
    "head_hash",
    "export_json",
    "export_pdf",
]

GENESIS_PREV = "0" * 64


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _entry_hash(index: int, prev: str, ts: str, record: dict[str, Any]) -> str:
    """Hash covers the link, the position and the time — not just the payload.

    Including `prev` is what chains it; including `index` stops a reordering
    attack that would otherwise preserve every individual hash.
    """
    return sha256_bytes(
        canonical_bytes({"index": index, "prev": prev, "ts": ts, "record": record})
    )


@dataclass(frozen=True)
class LogEntry:
    index: int
    prev: str
    ts: str
    record: dict[str, Any]
    hash: str

    def to_json(self) -> str:
        from asapproved.canonical import canonical_json

        return canonical_json(
            {
                "index": self.index,
                "prev": self.prev,
                "ts": self.ts,
                "record": self.record,
                "hash": self.hash,
            }
        )

    @staticmethod
    def from_raw(raw: dict[str, Any]) -> LogEntry:
        # Reject unknown top-level keys rather than ignoring them. Ignoring them
        # meant a field could be ADDED to a record — "decision_override":
        # "accepted by compliance" — and the chain still certified the line as
        # intact, because the digest only covered the four keys we read back.
        # Anyone reading the JSONL, or any downstream consumer, would see the
        # annotation inside a record the tool vouches for.
        unexpected = set(raw) - {"index", "prev", "ts", "record", "hash"}
        if unexpected:
            raise ValueError(f"unexpected fields in record: {sorted(unexpected)}")
        return LogEntry(
            index=raw["index"],
            prev=raw["prev"],
            ts=raw["ts"],
            record=raw["record"],
            hash=raw["hash"],
        )

    def recompute(self) -> str:
        return _entry_hash(self.index, self.prev, self.ts, self.record)


def read_entries(log_path: str | Path) -> Iterator[tuple[int, LogEntry | None, str]]:
    """Yield (line_number, entry_or_None, detail).

    `detail` is the raw line for a good entry, and the PARSE ERROR for a bad
    one — so a caller can report why a record is malformed rather than only
    that it is.

    A corrupted line is a verification failure, not an exception — the tamper demo
    depends on reporting *where* the damage is rather than crashing on it.
    """
    path = Path(log_path)
    if not path.exists():
        return
    # utf-8-sig: tolerate a BOM from Windows editors so a re-saved log fails only
    # on changed content, not on encoding. See the note in manifest.SignedManifest.read.
    with path.open("r", encoding="utf-8-sig") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                yield lineno, LogEntry.from_raw(json.loads(line)), line
            except Exception as exc:  # noqa: BLE001 - a bad line is a finding, not a crash
                # Carry the reason: "unexpected fields" and "not JSON" are very
                # different tampering stories, and the demo should say which.
                yield lineno, None, f"{type(exc).__name__}: {exc}"


def head_hash(log_path: str | Path) -> str:
    """The hash of the last entry, or GENESIS_PREV for an empty/absent log."""
    last = GENESIS_PREV
    for _, entry, _ in read_entries(log_path):
        if entry is not None:
            last = entry.hash
    return last


def append_record(log_path: str | Path, record: dict[str, Any]) -> LogEntry:
    """Append one record, linked to the current head. Returns the new entry."""
    assert_no_floats(record)
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    index = 0
    prev = GENESIS_PREV
    for _, entry, _ in read_entries(path):
        if entry is None:
            raise ValueError(
                "refusing to append to a log with a malformed line — "
                "run `asapproved verify-log` first"
            )
        index = entry.index + 1
        prev = entry.hash

    ts = _utc_now_iso()
    entry = LogEntry(
        index=index,
        prev=prev,
        ts=ts,
        record=record,
        hash=_entry_hash(index, prev, ts, record),
    )
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry.to_json() + "\n")
    return entry


@dataclass(frozen=True)
class ChainResult:
    ok: bool
    entries: int
    first_bad_index: int | None = None
    first_bad_line: int | None = None
    reason: str = "chain intact"
    head: str = GENESIS_PREV

    def __bool__(self) -> bool:
        return self.ok


def verify_chain(log_path: str | Path) -> ChainResult:
    """Walk the chain and report the first record that fails, and why."""
    path = Path(log_path)
    if not path.exists():
        return ChainResult(False, 0, reason=f"no such log: {path}")

    expected_prev = GENESIS_PREV
    expected_index = 0
    count = 0
    head = GENESIS_PREV

    for lineno, entry, _raw in read_entries(path):
        if entry is None:
            # When an entry fails to parse, `read_entries` yields the reason in
            # place of the raw line: "unexpected fields" and "not valid JSON"
            # are different tampering stories and the demo should name which.
            why = _raw or "not valid JSON"
            return ChainResult(
                False,
                count,
                first_bad_index=expected_index,
                first_bad_line=lineno,
                reason=f"record at line {lineno} is malformed: {why}",
                head=head,
            )
        if entry.index != expected_index:
            return ChainResult(
                False,
                count,
                first_bad_index=entry.index,
                first_bad_line=lineno,
                reason=(
                    f"record out of order at line {lineno}: "
                    f"expected index {expected_index}, found {entry.index}"
                ),
                head=head,
            )
        if entry.prev != expected_prev:
            return ChainResult(
                False,
                count,
                first_bad_index=entry.index,
                first_bad_line=lineno,
                reason=(
                    f"broken link at record {entry.index}: it points at "
                    f"{entry.prev[:12]}… but the previous record hashes to {expected_prev[:12]}…"
                ),
                head=head,
            )
        recomputed = entry.recompute()
        if recomputed != entry.hash:
            return ChainResult(
                False,
                count,
                first_bad_index=entry.index,
                first_bad_line=lineno,
                reason=(
                    f"record {entry.index} has been altered: it stores "
                    f"{entry.hash[:12]}… but its contents hash to {recomputed[:12]}…"
                ),
                head=head,
            )
        count += 1
        expected_index = entry.index + 1
        expected_prev = entry.hash
        head = entry.hash

    return ChainResult(True, count, head=head)


def export_json(log_path: str | Path, out_path: str | Path) -> Path:
    """Export the log plus its verification status as one JSON document."""
    result = verify_chain(log_path)
    entries = [
        {"index": e.index, "ts": e.ts, "record": e.record, "hash": e.hash}
        for _, e, _ in read_entries(log_path)
        if e is not None
    ]
    doc = {
        "exported_at": _utc_now_iso(),
        "entries": entries,
        "verification": {
            "ok": result.ok,
            "reason": result.reason,
            "entries": result.entries,
            "head": result.head,
            "first_bad_index": result.first_bad_index,
        },
        "retention_note": (
            "Retain per COBS 4.11.1R: 3 years by default, 5 years for MiFID business. "
            "Flags items for compliance review; not legal advice."
        ),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def export_pdf(log_path: str | Path, out_path: str | Path):  # noqa: ANN201
    raise NotImplementedError("Phase 5")
