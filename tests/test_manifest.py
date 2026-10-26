"""C1 — approval manifest signing and verification."""

from __future__ import annotations

import json

import pytest

from asapproved.canonical import assert_no_floats, canonical_bytes, sha256_file
from asapproved.manifest import (
    ApprovalManifest,
    SignedManifest,
    generate_key,
    sign_manifest,
    verify_manifest,
)


@pytest.fixture()
def key(tmp_path):
    return generate_key(tmp_path / "manifest_ed25519.key")


@pytest.fixture()
def master(tmp_path):
    p = tmp_path / "northfield_card_01.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pretend this is an approved credit card ad" * 10)
    return p


def _manifest(master):
    return ApprovalManifest.for_master(
        master,
        approver="compliance@example.test",
        investment_type="cryptoassets",
        enhancement_settings={"image_touchups": "OPT_OUT", "image_animation": "OPT_OUT"},
        placements=["feed", "reels"],
        notes="Representative 24.9% APR on screen and spoken.",
    )


def test_generate_key_writes_private_and_public(tmp_path):
    path = generate_key(tmp_path / "k.key")
    assert path.exists()
    assert path.with_suffix(".key.pub").exists()
    assert b"PRIVATE KEY" in path.read_bytes()


def test_generate_key_refuses_silent_overwrite(tmp_path):
    path = generate_key(tmp_path / "k.key")
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        generate_key(path)
    assert path.read_bytes() == original, "an accidental re-keygen must not destroy the signer"
    generate_key(path, force=True)
    assert path.read_bytes() != original


def test_sign_then_verify_roundtrip(tmp_path, key, master):
    signed = sign_manifest(_manifest(master), key)
    out = signed.write(tmp_path / "m.manifest.json")

    result = verify_manifest(out)
    assert result.ok, result.reason
    assert result.payload["master_sha256"] == sha256_file(master)
    assert result.payload["investment_type"] == "cryptoassets"
    # Without a pinned key we must say so rather than imply proof of identity.
    assert result.key_pinned is False
    assert "self-signed" in result.reason


def test_verify_with_pinned_key(tmp_path, key, master):
    signed = sign_manifest(_manifest(master), key)
    out = signed.write(tmp_path / "m.json")

    good = verify_manifest(out, trusted_public_key=key.with_suffix(".key.pub"))
    assert good.ok and good.key_pinned
    assert "self-signed" not in good.reason

    other = generate_key(tmp_path / "attacker.key")
    bad = verify_manifest(out, trusted_public_key=other.with_suffix(".key.pub"))
    assert not bad.ok
    assert "not the trusted key" in bad.reason


def test_altered_payload_fails_verification(tmp_path, key, master):
    signed = sign_manifest(_manifest(master), key)
    out = signed.write(tmp_path / "m.json")

    raw = json.loads(out.read_text(encoding="utf-8"))
    raw["payload"]["approver"] = "someone.else@example.test"
    out.write_text(json.dumps(raw), encoding="utf-8")

    result = verify_manifest(out)
    assert not result.ok
    assert "altered" in result.reason


def test_resigning_altered_content_is_caught_only_by_pinning(tmp_path, key, master):
    """The honest limitation, pinned by test so nobody forgets it.

    An attacker who can rewrite the file can also mint a key and re-sign. The
    signature then verifies. ONLY pinning the trusted key catches this — which is
    exactly why `key_pinned` is reported to the UI rather than hidden.
    """
    signed = sign_manifest(_manifest(master), key)
    out = signed.write(tmp_path / "m.json")

    from asapproved.manifest import _public_pem, load_private_key

    attacker = generate_key(tmp_path / "attacker.key")
    forged_payload = dict(signed.payload, approver="attacker@example.test")
    priv = load_private_key(attacker)
    SignedManifest(
        payload=forged_payload,
        signature=priv.sign(canonical_bytes(forged_payload)).hex(),
        public_key=_public_pem(priv.public_key()),
    ).write(out)

    assert verify_manifest(out).ok, "re-signed content verifies — this is the known limit"
    pinned = verify_manifest(out, trusted_public_key=key.with_suffix(".key.pub"))
    assert not pinned.ok and "not the trusted key" in pinned.reason


def test_swapped_master_is_detected(tmp_path, key, master):
    signed = sign_manifest(_manifest(master), key)
    out = signed.write(tmp_path / "m.json")
    assert verify_manifest(out, master_path=master).ok

    master.write_bytes(master.read_bytes() + b"an extra frame nobody approved")
    result = verify_manifest(out, master_path=master)
    assert not result.ok
    assert "does not match the approved record" in result.reason


def test_prescribed_text_apostrophe_survives_signing(tmp_path, key, master):
    """COBS 4.12A.11R text contains a typographic apostrophe in "Don't".

    If canonical encoding mangled it, R11 would compare mangled text and the
    signature would differ between writer and verifier. Pinned explicitly.
    """
    m = ApprovalManifest.for_master(
        master,
        approver="a@example.test",
        notes="Don’t invest unless you’re prepared to lose all the money you invest.",
    )
    out = sign_manifest(m, key).write(tmp_path / "m.json")
    result = verify_manifest(out)
    assert result.ok
    assert "’" in result.payload["notes"]
    assert "\\u2019" not in out.read_text(encoding="utf-8")


def test_floats_are_rejected_in_signed_payloads():
    """Floats do not round-trip reliably, so measurements use fixed units."""
    with pytest.raises(TypeError, match="float at"):
        assert_no_floats({"seconds_visible": 1.2})
    with pytest.raises(TypeError, match=r"\$\.findings\[0\]\.value"):
        assert_no_floats({"findings": [{"value": 0.98}]})
    assert_no_floats({"ms_visible": 1200, "ratio_bp": 9800, "label": "ok"})  # must not raise


def test_bom_does_not_look_like_tampering(tmp_path, key, master):
    """Windows tooling adds a BOM on re-save; that is not an alteration.

    Found the hard way: PowerShell's `Out-File -Encoding utf8` writes one, and a
    strict utf-8 read reported "unreadable manifest" — which in a compliance tool
    reads as a tamper alarm. Crying wolf on benign re-saves is how people learn to
    ignore the alarm, so the content check must be what decides.
    """
    signed = sign_manifest(_manifest(master), key)
    out = signed.write(tmp_path / "m.json")
    out.write_bytes(b"\xef\xbb\xbf" + out.read_bytes())

    result = verify_manifest(out)
    assert result.ok, result.reason

    # ...but a real edit under the BOM must still fail.
    raw = json.loads(out.read_text(encoding="utf-8-sig"))
    raw["payload"]["approver"] = "someone.else@example.test"
    out.write_bytes(b"\xef\xbb\xbf" + json.dumps(raw).encode("utf-8"))
    assert not verify_manifest(out).ok


def test_missing_fields_are_reported_not_raised(tmp_path):
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"payload": {}}), encoding="utf-8")
    result = verify_manifest(bad)
    assert not result.ok
    assert "missing fields" in result.reason
