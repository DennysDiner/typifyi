"""Configuration: YAML files under config/, secrets from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("RTI_ROOT", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
REGISTRY_DIR = ROOT / "registry"
LEGAL_DIR = ROOT / "legal"
DATA_DIR = Path(os.environ.get("RTI_DATA_DIR", ROOT / "data"))


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Settings:
    db_path: Path = field(default_factory=lambda: DATA_DIR / "rti.db")
    archive_dir: Path = field(default_factory=lambda: DATA_DIR / "archive")
    user_agent: str = field(
        default_factory=lambda: os.environ.get(
            "RTI_USER_AGENT",
            "tas-rti-tracker/0.1 (+public-interest RTI monitoring; contact: "
            + os.environ.get("RTI_CONTACT_EMAIL", "set RTI_CONTACT_EMAIL")
            + ")",
        )
    )
    contact_email: str = field(default_factory=lambda: os.environ.get("RTI_CONTACT_EMAIL", ""))
    anthropic_api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: os.environ.get("RTI_LLM_MODEL", "claude-sonnet-5"))
    ntfy_url: str | None = field(default_factory=lambda: os.environ.get("RTI_NTFY_URL"))
    ntfy_token: str | None = field(default_factory=lambda: os.environ.get("RTI_NTFY_TOKEN"))
    smtp_host: str | None = field(default_factory=lambda: os.environ.get("RTI_SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("RTI_SMTP_PORT", "587")))
    smtp_user: str | None = field(default_factory=lambda: os.environ.get("RTI_SMTP_USER"))
    smtp_password: str | None = field(default_factory=lambda: os.environ.get("RTI_SMTP_PASSWORD"))
    alert_email_to: str | None = field(default_factory=lambda: os.environ.get("RTI_ALERT_EMAIL_TO"))
    web_auth_user: str | None = field(default_factory=lambda: os.environ.get("RTI_WEB_USER"))
    web_auth_password: str | None = field(default_factory=lambda: os.environ.get("RTI_WEB_PASSWORD"))
    scheduler: dict = field(default_factory=lambda: load_yaml(CONFIG_DIR / "scheduler.yaml"))
    watchlist: dict = field(default_factory=lambda: load_yaml(CONFIG_DIR / "watchlist.yaml"))
    alerts: dict = field(default_factory=lambda: load_yaml(CONFIG_DIR / "alerts.yaml"))


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
