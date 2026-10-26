"""Phase 0 tests: the scaffold imports, the CLI runs, the rulebook parses, and no
secret leaks into a readout. Real module tests arrive with the modules.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from asapproved import RULEBOOK_VERSION, __version__
from asapproved.cli import app
from asapproved.config import REPO_ROOT, mask, settings

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_doctor_runs_and_masks_secrets() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    # Whatever is in .env, a doctor readout must never contain a full secret.
    for secret in (
        settings.models.api_key,
        settings.marketing.access_token,
        settings.marketing.app_secret,
        settings.graph.password,
    ):
        if secret:
            assert secret not in result.stdout


def test_mask_never_reveals_short_secrets() -> None:
    assert mask(None) == "<unset>"
    assert mask("abc") == "***"
    assert mask("0123456789abcdef") == "0123…cdef"


def test_unbuilt_commands_exit_cleanly() -> None:
    """Stubs must say which phase they land in, not raise NotImplementedError at the user."""
    for cmd in ("check", "drift", "bench", "demo"):
        args = [cmd, "x"] if cmd == "check" else [cmd]
        result = runner.invoke(app, args)
        assert result.exit_code == 2, cmd
        assert "Not built yet" in result.stdout, cmd


def test_phase2_commands_are_wired() -> None:
    """keygen/approve/verify-* are built — they must no longer claim otherwise."""
    for cmd in ("keygen", "approve", "verify-manifest", "verify-log"):
        result = runner.invoke(app, [cmd, "--help"])
        assert result.exit_code == 0, cmd
        assert "Not built yet" not in result.stdout, cmd


def test_rulebook_parses_and_is_complete() -> None:
    path = REPO_ROOT / "asapproved" / "rules" / "rulebook_uk_v1.yaml"
    book = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert book["version"] == RULEBOOK_VERSION
    ids = [r["id"] for r in book["rules"]]
    assert ids == [f"R{n}" for n in range(1, 13)] + ["B1"]
    for rule in book["rules"]:
        for field in ("title", "citation", "paraphrase", "inputs", "logic", "severity"):
            assert rule.get(field) is not None, f"{rule['id']} missing {field}"
        assert rule["severity"] in {"block", "review", "info"}
    # B1 is a TV convention, not a legal test — it must stay benchmark-only.
    b1 = next(r for r in book["rules"] if r["id"] == "B1")
    assert b1["benchmark_only"] is True


def test_prescribed_texts_are_verbatim_and_distinct() -> None:
    """COBS 4.12A.11R, verified 26 Oct 2026 (DECISIONS.md D-007).

    These four strings are quoted law. A stray edit here silently breaks R11 in the
    worst way — it would pass altered warnings and flag correct ones — so they are
    pinned by test rather than left to review.
    """
    path = REPO_ROOT / "asapproved" / "rules" / "rulebook_uk_v1.yaml"
    texts = yaml.safe_load(path.read_text(encoding="utf-8"))["prescribed_texts"]

    expected = {
        "non_readily_realisable_securities": (
            "Don't invest unless you're prepared to lose all the money you invest. This is a "
            "high-risk investment and you are unlikely to be protected if something goes wrong."
        ),
        "p2p_agreements": (
            "Don't invest unless you're prepared to lose money. This is a high-risk investment. "
            "You may not be able to access your money easily and are unlikely to be protected "
            "if something goes wrong."
        ),
        "long_term_asset_fund": (
            "This is a high-risk investment, and assets may take a long time to buy and sell. "
            "Only invest if you can wait (possibly several years) to get your money back. You "
            "do not have protection against poor performance."
        ),
        "cryptoassets": (
            "Don't invest unless you're prepared to lose all the money you invest. This is a "
            "high-risk investment and you should not expect to be protected if something goes "
            "wrong."
        ),
    }
    assert texts == expected

    # The crypto and NRRS variants differ by five words only. R11 must never collapse
    # them into one "prescribed text" — that is the whole reason for the per-type table.
    assert texts["cryptoassets"] != texts["non_readily_realisable_securities"]
    assert "should not expect to be protected" in texts["cryptoassets"]
    assert "unlikely to be protected" in texts["non_readily_realisable_securities"]


def test_r11_selects_prescribed_text_by_investment_type() -> None:
    path = REPO_ROOT / "asapproved" / "rules" / "rulebook_uk_v1.yaml"
    book = yaml.safe_load(path.read_text(encoding="utf-8"))
    r11 = next(r for r in book["rules"] if r["id"] == "R11")
    assert "investment_type" in r11["inputs"]
    assert r11["citation"] == "COBS 4.12A.11R"


def test_env_example_has_no_values() -> None:
    """.env.example carries names only — a value in it would be a committed secret."""
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    allowed_defaults = {
        "META_SPARK_MODEL",
        "META_SAM_MODEL",
        "META_TRANSCRIBE_MODEL",
        "NEO4J_URI",
        "NEO4J_USER",
        "ASAPPROVED_SIGNING_KEY_PATH",
        "ASAPPROVED_MODE",
        "ASAPPROVED_DATA_DIR",
        "ASAPPROVED_SPARK_EFFORT",
    }
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if value:
            assert key in allowed_defaults, f"{key} has a value in .env.example"


def test_gitignore_blocks_secrets() -> None:
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "*.key", "data/cache/", ".streamlit/secrets.toml"):
        assert pattern in text, pattern


def test_data_dir_is_inside_repo() -> None:
    assert Path(settings.data_dir).is_relative_to(REPO_ROOT)
