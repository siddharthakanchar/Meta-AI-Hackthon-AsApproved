"""Central configuration. Loads from .env, never prints secrets.

Rules enforced here (playbook §17):
- secrets only ever come from the environment / .env, never from code or git;
- any secret that gets displayed goes through `mask()`;
- `MODE` gates all network access: in `demo` mode every model call must be a cache hit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

Mode = Literal["demo", "live"]


def mask(secret: str | None) -> str:
    """Render a secret safely for logs and the UI: `abcd…wxyz` or `<unset>`."""
    if not secret:
        return "<unset>"
    if len(secret) <= 10:
        return "*" * len(secret)
    return f"{secret[:4]}…{secret[-4:]}"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


META_API_BASE = "https://api.meta.ai/v1"  # verified 26 Oct 2026, DECISIONS.md D-006


@dataclass(frozen=True)
class ModelConfig:
    """Meta Model API. Verified against the live docs on 26 Oct 2026 — DECISIONS.md D-006."""

    api_key: str = field(default_factory=lambda: _env("META_MODEL_API_KEY"))
    base_url: str = field(default_factory=lambda: _env("META_MODEL_BASE_URL", META_API_BASE))
    spark_model: str = field(default_factory=lambda: _env("META_SPARK_MODEL", "muse-spark-1.3"))
    sam_model: str = field(default_factory=lambda: _env("META_SAM_MODEL", "sam-3.1"))
    transcribe_model: str = field(
        default_factory=lambda: _env("META_TRANSCRIBE_MODEL", "muse-voice-transcribe-1.0")
    )
    spark_effort: str = field(default_factory=lambda: _env("ASAPPROVED_SPARK_EFFORT", "low"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class MarketingConfig:
    """Meta Marketing API. `path` (A/B/C per playbook §8) is recorded in DECISIONS.md."""

    app_id: str = field(default_factory=lambda: _env("META_APP_ID"))
    app_secret: str = field(default_factory=lambda: _env("META_APP_SECRET"))
    access_token: str = field(default_factory=lambda: _env("META_ACCESS_TOKEN"))
    ad_account_id: str = field(default_factory=lambda: _env("META_AD_ACCOUNT_ID"))
    page_id: str = field(default_factory=lambda: _env("META_PAGE_ID"))
    api_version: str = field(default_factory=lambda: _env("META_GRAPH_API_VERSION"))

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.ad_account_id)

    @property
    def graph_base(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"


@dataclass(frozen=True)
class GraphConfig:
    uri: str = field(default_factory=lambda: _env("NEO4J_URI", "bolt://localhost:7687"))
    user: str = field(default_factory=lambda: _env("NEO4J_USER", "neo4j"))
    password: str = field(default_factory=lambda: _env("NEO4J_PASSWORD"))

    @property
    def configured(self) -> bool:
        return bool(self.password)


@dataclass(frozen=True)
class Settings:
    mode: Mode = field(default_factory=lambda: _env("ASAPPROVED_MODE", "demo"))  # type: ignore[assignment]
    data_dir: Path = field(
        default_factory=lambda: (REPO_ROOT / _env("ASAPPROVED_DATA_DIR", "data")).resolve()
    )
    signing_key_path: Path = field(
        default_factory=lambda: (
            REPO_ROOT / _env("ASAPPROVED_SIGNING_KEY_PATH", "data/keys/manifest_ed25519.key")
        ).resolve()
    )
    models: ModelConfig = field(default_factory=ModelConfig)
    marketing: MarketingConfig = field(default_factory=MarketingConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)

    # --- derived paths -------------------------------------------------
    @property
    def masters_dir(self) -> Path:
        return self.data_dir / "masters"

    @property
    def variants_dir(self) -> Path:
        return self.data_dir / "variants"

    @property
    def labels_dir(self) -> Path:
        return self.data_dir / "labels"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def evidence_dir(self) -> Path:
        return self.data_dir / "evidence"

    @property
    def fixtures_dir(self) -> Path:
        return self.data_dir / "fixtures"

    @property
    def costs_log(self) -> Path:
        return self.data_dir / "costs.jsonl"

    @property
    def offline(self) -> bool:
        """True when no network call is permitted — every model result must come from cache."""
        return self.mode == "demo"

    def ensure_dirs(self) -> None:
        for p in (
            self.masters_dir,
            self.variants_dir,
            self.labels_dir,
            self.cache_dir,
            self.evidence_dir,
            self.fixtures_dir,
            self.signing_key_path.parent,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def redacted(self) -> dict[str, str]:
        """Everything needed for a `doctor` readout, with every secret masked."""
        return {
            "mode": self.mode,
            "data_dir": str(self.data_dir),
            "model_api_key": mask(self.models.api_key),
            "model_base_url": self.models.base_url or "<unset>",
            "spark_model": self.models.spark_model,
            "sam_model": self.models.sam_model,
            "transcribe_model": self.models.transcribe_model,
            "spark_effort": self.models.spark_effort,
            "meta_app_id": mask(self.marketing.app_id),
            "meta_access_token": mask(self.marketing.access_token),
            "meta_ad_account_id": self.marketing.ad_account_id or "<unset>",
            "meta_page_id": mask(self.marketing.page_id),
            "graph_api_version": self.marketing.api_version or "<unset>",
            "neo4j_uri": self.graph.uri,
            "neo4j_password": mask(self.graph.password),
        }


settings = Settings()
