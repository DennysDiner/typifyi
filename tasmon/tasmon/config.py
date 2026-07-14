"""Load and validate config.yaml. Everything user-editable lives there."""

import os
import re

import yaml

DEFAULT_CONFIG_PATH = os.environ.get("TASMON_CONFIG", "config.yaml")


class Config:
    def __init__(self, raw: dict, path: str):
        self.raw = raw
        self.path = path
        self.base_dir = os.path.dirname(os.path.abspath(path))

    @classmethod
    def load(cls, path: str = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls(raw, path)

    # --- paths ---
    def _abspath(self, p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(self.base_dir, p)

    @property
    def db_path(self) -> str:
        return self._abspath(self.raw.get("storage", {}).get("db_path", "data/tasmon.db"))

    @property
    def digest_dir(self) -> str:
        return self._abspath(self.raw.get("storage", {}).get("digest_dir", "digests"))

    # --- sources ---
    @property
    def sources(self) -> list:
        return self.raw.get("sources", [])

    def sources_for_schedule(self, schedule: str) -> list:
        return [s for s in self.sources if s.get("schedule", "tier1") == schedule]

    # --- fetching ---
    @property
    def user_agent(self) -> str:
        return self.raw.get("fetching", {}).get(
            "user_agent",
            "tasmon/0.1 (personal news monitor; contact via config)",
        )

    @property
    def timeout(self) -> int:
        return self.raw.get("fetching", {}).get("timeout_seconds", 30)

    @property
    def respect_robots(self) -> bool:
        return self.raw.get("fetching", {}).get("respect_robots", True)

    # --- watchlist / scoring ---
    @property
    def watchlist(self) -> list:
        return self.raw.get("watchlist", [])

    @property
    def salience_terms(self) -> dict:
        return self.raw.get("scoring", {}).get("salience_terms", {})

    @property
    def tier_weights(self) -> dict:
        return {int(k): float(v) for k, v in self.raw.get("scoring", {}).get(
            "tier_weights", {1: 1.0, 2: 0.6, 3: 0.5}).items()}

    @property
    def recency_half_life_hours(self) -> float:
        return float(self.raw.get("scoring", {}).get("recency_half_life_hours", 48))

    @property
    def near_duplicate_threshold(self) -> float:
        return float(self.raw.get("scoring", {}).get("near_duplicate_threshold", 0.8))

    @property
    def portfolios(self) -> dict:
        return self.raw.get("portfolios", {})

    # --- alerts ---
    @property
    def alert_rules(self) -> list:
        return self.raw.get("alerts", {}).get("rules", [])

    @property
    def alert_channel(self) -> str:
        return self.raw.get("alerts", {}).get("channel", "terminal")

    # --- email ---
    @property
    def email(self) -> dict:
        return self.raw.get("email", {})

    def smtp_password(self) -> str:
        env = self.email.get("password_env", "TASMON_SMTP_PASS")
        return os.environ.get(env, "")

    # --- digest ---
    @property
    def digest_email_enabled(self) -> bool:
        return bool(self.raw.get("digest", {}).get("email", False))

    @property
    def source_stale_days(self) -> int:
        return int(self.raw.get("digest", {}).get("source_stale_days", 3))

    # --- summarisation ---
    @property
    def summarization(self) -> dict:
        return self.raw.get("summarization", {"enabled": False})


def compile_terms(terms) -> list:
    """Compile a list of match terms into regexes.

    Terms are matched case-insensitively on word boundaries. A trailing or
    embedded '*' acts as a wildcard over word characters, so 'liquidat*'
    matches liquidate/liquidation/liquidator.
    """
    compiled = []
    for t in terms:
        pattern = re.escape(t).replace(r"\*", r"\w*")
        compiled.append(re.compile(r"(?<!\w)" + pattern + r"(?!\w)", re.IGNORECASE))
    return compiled
