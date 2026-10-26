"""C1 — approval manifests.

Approving a master records what was approved, by whom, when, against which
rulebook, and with which Advantage+ enhancement settings in force at that moment
— then signs the lot with Ed25519. Later, when Meta has reshaped the creative,
the manifest is what "approved" is measured against.

The settings snapshot is the part people miss. Without it, R2 (settings drift)
has nothing to compare against: you cannot show an enhancement was switched on
after approval unless you recorded that it was off at approval.

Threat model, stated honestly:
  This detects alteration of an approved record, and proves which key signed it.
  It does NOT prove the signing key belongs to a particular person — there is no
  PKI here. A firm deploying this would put the private key in an HSM or KMS and
  bind the public key to an identity. `verify` therefore supports pinning a
  trusted public key, and says plainly when it is only checking self-consistency,
  because a signature verified against a key carried inside the same file proves
  nothing on its own.
"""

from __future__ import annotations

import os
import stat
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from asapproved import RULEBOOK_VERSION
from asapproved.canonical import (
    assert_no_floats,
    canonical_bytes,
    canonical_json,
    sha256_file,
)

__all__ = [
    "ApprovalManifest",
    "SignedManifest",
    "VerifyResult",
    "generate_key",
    "load_private_key",
    "sign_manifest",
    "verify_manifest",
    "MANIFEST_SCHEMA_VERSION",
]

MANIFEST_SCHEMA_VERSION = 1
SIGNATURE_ALGORITHM = "ed25519"


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------
# keys
# --------------------------------------------------------------------------


def generate_key(path: str | Path, force: bool = False) -> Path:
    """Write a new Ed25519 private key (PEM) plus its `.pub`, and return the path.

    The private key is written unencrypted because the demo has to run unattended;
    that is a demo compromise and is labelled as one in the README. It is created
    with owner-only permissions, and `.gitignore` excludes `*.key` and `*.pem`.
    """
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; pass force=True to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)

    private = Ed25519PrivateKey.generate()
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # Create with restrictive permissions rather than relaxing them afterwards,
    # so the key is never briefly world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)

    pub_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.with_suffix(path.suffix + ".pub").write_bytes(pub_pem)
    return path


def load_private_key(path: str | Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError(f"{path} is not an Ed25519 private key")
    return key


def _public_pem(key: Ed25519PublicKey) -> str:
    return key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _load_public_pem(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("not an Ed25519 public key")
    return key


# --------------------------------------------------------------------------
# the manifest
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalManifest:
    """What was approved. Signed as canonical JSON — see `asapproved.canonical`."""

    master_id: str
    master_sha256: str
    master_filename: str
    approver: str
    approved_at: str
    rulebook_version: str = RULEBOOK_VERSION
    schema_version: int = MANIFEST_SCHEMA_VERSION

    # Which prescribed warning applies (COBS 4.12A.11R has four variants — D-007).
    # R11 cannot run without this, so it is part of the approved record, not a
    # runtime guess.
    investment_type: str | None = None

    # Advantage+ enhancement settings in force at approval: {feature: OPT_IN|OPT_OUT}.
    # R2 diffs live settings against this snapshot.
    enhancement_settings: dict[str, str] = field(default_factory=dict)

    # Free-text note from the approver, and the placements this approval covers.
    notes: str = ""
    placements: list[str] = field(default_factory=list)

    @staticmethod
    def for_master(
        master_path: str | Path,
        approver: str,
        *,
        master_id: str | None = None,
        investment_type: str | None = None,
        enhancement_settings: dict[str, str] | None = None,
        placements: list[str] | None = None,
        notes: str = "",
        approved_at: str | None = None,
    ) -> ApprovalManifest:
        master_path = Path(master_path)
        return ApprovalManifest(
            master_id=master_id or master_path.stem,
            master_sha256=sha256_file(master_path),
            master_filename=master_path.name,
            approver=approver,
            approved_at=approved_at or _utc_now_iso(),
            investment_type=investment_type,
            enhancement_settings=dict(enhancement_settings or {}),
            placements=list(placements or []),
            notes=notes,
        )

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        assert_no_floats(data)
        return data


@dataclass(frozen=True)
class SignedManifest:
    payload: dict[str, Any]
    signature: str  # hex
    public_key: str  # PEM
    algorithm: str = SIGNATURE_ALGORITHM

    def to_json(self) -> str:
        return canonical_json(
            {
                "payload": self.payload,
                "signature": self.signature,
                "public_key": self.public_key,
                "algorithm": self.algorithm,
            }
        )

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @staticmethod
    def read(path: str | Path) -> SignedManifest:
        import json

        # utf-8-sig, not utf-8: a byte-order mark is not valid JSON, but Windows
        # tooling adds one routinely (PowerShell's `Out-File -Encoding utf8` does).
        # A re-saved manifest must fail verification only if its CONTENT changed —
        # reporting "unreadable" for a BOM would cry tamper at an innocent edit and
        # teach users to ignore the alarm.
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        missing = {"payload", "signature", "public_key"} - raw.keys()
        if missing:
            raise ValueError(f"manifest missing fields: {sorted(missing)}")
        return SignedManifest(
            payload=raw["payload"],
            signature=raw["signature"],
            public_key=raw["public_key"],
            algorithm=raw.get("algorithm", SIGNATURE_ALGORITHM),
        )


def sign_manifest(manifest: ApprovalManifest, key_path: str | Path) -> SignedManifest:
    private = load_private_key(key_path)
    payload = manifest.payload()
    signature = private.sign(canonical_bytes(payload))
    return SignedManifest(
        payload=payload,
        signature=signature.hex(),
        public_key=_public_pem(private.public_key()),
    )


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str
    payload: dict[str, Any] | None = None
    key_pinned: bool = False
    master_checked: bool = False

    def __bool__(self) -> bool:
        return self.ok


def verify_manifest(
    path: str | Path,
    *,
    trusted_public_key: str | Path | None = None,
    master_path: str | Path | None = None,
) -> VerifyResult:
    """Verify a manifest's signature, and optionally the master it describes.

    `trusted_public_key` pins the expected signer. Without it this only shows the
    file is internally consistent — anyone can mint a key and re-sign altered
    content — and `key_pinned` is False so callers (and the UI) can say so rather
    than overclaim.

    `master_path` additionally re-hashes the master and compares it to the record,
    which is what catches "the approved file itself was swapped".
    """
    try:
        signed = SignedManifest.read(path)
    except Exception as exc:  # noqa: BLE001 - surfaced as a reason string
        return VerifyResult(False, f"unreadable manifest: {exc}")

    if signed.algorithm != SIGNATURE_ALGORITHM:
        return VerifyResult(False, f"unsupported algorithm: {signed.algorithm!r}")

    key_pinned = False
    if trusted_public_key is not None:
        pinned = Path(trusted_public_key)
        pinned_pem = (
            pinned.read_text(encoding="utf-8") if pinned.exists() else str(trusted_public_key)
        )
        if pinned_pem.strip() != signed.public_key.strip():
            return VerifyResult(False, "signer is not the trusted key", key_pinned=True)
        key_pinned = True

    try:
        public = _load_public_pem(signed.public_key)
        public.verify(bytes.fromhex(signed.signature), canonical_bytes(signed.payload))
    except InvalidSignature:
        return VerifyResult(
            False, "signature does not match payload (manifest altered)", key_pinned=key_pinned
        )
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(False, f"signature check failed: {exc}", key_pinned=key_pinned)

    master_checked = False
    if master_path is not None:
        actual = sha256_file(master_path)
        expected = signed.payload.get("master_sha256")
        if actual != expected:
            return VerifyResult(
                False,
                f"master does not match the approved record "
                f"(expected {expected[:12]}…, got {actual[:12]}…)",
                payload=signed.payload,
                key_pinned=key_pinned,
                master_checked=True,
            )
        master_checked = True

    reason = "signature valid"
    if not key_pinned:
        reason += " (self-signed: no trusted key pinned, so this proves integrity, not identity)"
    if master_checked:
        reason += "; master hash matches"
    return VerifyResult(
        True,
        reason,
        payload=signed.payload,
        key_pinned=key_pinned,
        master_checked=master_checked,
    )
