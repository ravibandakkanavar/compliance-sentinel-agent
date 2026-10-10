"""Runtime settings, read from environment variables and an optional .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SENTINEL_", extra="ignore")

    # Storage. An empty database_url selects the in-memory store (tests, dry runs).
    database_url: str = ""
    redis_url: str = "redis://localhost:6379"

    # Model. Credentials come from ANTHROPIC_API_KEY, read by the SDK itself.
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    enable_fallbacks: bool = True

    # Embeddings. "fastembed" runs a local ONNX model; "hash" needs no download.
    embedder: str = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Audit limits.
    target_repo: str = str(REPO_ROOT / "demo_repo")
    sources_file: str = str(PACKAGE_DIR / "sources.yaml")
    max_chunks_per_run: int = 60
    obligation_batch_size: int = 6
    whole_repo_char_budget: int = 150_000
    snippet_char_budget: int = 40_000

    # Output.
    data_dir: str = str(REPO_ROOT / "data")
    alert_min_severity: str = "critical"

    # Alerts. Each channel is skipped when its settings are empty.
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_from: str = ""
    alert_email_to: str = ""

    # Queue and manual trigger.
    queue_name: str = "sentinel-runs"
    trigger_token: str = ""

    @property
    def reports_dir(self) -> Path:
        return Path(self.data_dir) / "reports"

    @property
    def snapshots_dir(self) -> Path:
        return Path(self.data_dir) / "snapshots"


@lru_cache
def get_settings() -> Settings:
    return Settings()
