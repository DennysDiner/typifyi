"""Configuration: paths, politeness settings and budgets.

Everything is overridable by environment variable so that the same code runs in
GitHub Actions, in a Codespace, and in tests without a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from .archive import ArchiveWriter, LocalGzipArchiveWriter, S3ArchiveWriter
from .fetcher import DEFAULT_CONTACT, Fetcher


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


@dataclass
class Config:
    root: Path = Path(".")
    state_dir: Path = Path("state")
    archive_dir: Path = Path("archive")
    records_dir: Path = Path("records")
    review_dir: Path = Path("records/review")
    outputs_dir: Path = Path("outputs")
    watchlist_path: Path = Path("watchlist.yml")
    docs_dir: Path = Path("adapters")

    contact: str = DEFAULT_CONTACT
    user_agent: str | None = None
    min_interval_s: float = 2.0
    timeout_s: float = 45.0
    max_attempts: int = 4
    respect_robots: bool = True

    max_detail_pages: int = 25
    max_documents: int = 6
    max_pdf_pages: int = 400
    max_body_chars: int = 20_000

    archive_backend: str = "local"
    s3_bucket: str = ""
    s3_prefix: str = "archive"
    s3_endpoint_url: str | None = None

    labels_enabled: bool = True
    extra: dict[str, str] = field(default_factory=dict)

    # -- derived paths ------------------------------------------------------

    def path(self, value: Path | str) -> Path:
        value = Path(value)
        return value if value.is_absolute() else self.root / value

    @property
    def state_path(self) -> Path:
        return self.path(self.state_dir)

    @property
    def archive_path(self) -> Path:
        return self.path(self.archive_dir)

    @property
    def records_path(self) -> Path:
        return self.path(self.records_dir)

    @property
    def review_path(self) -> Path:
        return self.path(self.review_dir)

    @property
    def outputs_path(self) -> Path:
        return self.path(self.outputs_dir)

    @property
    def watchlist_file(self) -> Path:
        return self.path(self.watchlist_path)

    @property
    def heartbeat_file(self) -> Path:
        return self.state_path / "heartbeat.json"

    @property
    def runs_file(self) -> Path:
        return self.state_path / "runs.json"

    # -- factories ----------------------------------------------------------

    @classmethod
    def from_env(cls, root: Path | str | None = None, **overrides) -> "Config":
        config = cls(
            root=Path(root or os.environ.get("TNW_ROOT", ".")),
            contact=os.environ.get("TNW_CONTACT", DEFAULT_CONTACT),
            user_agent=os.environ.get("TNW_USER_AGENT") or None,
            min_interval_s=_env_float("TNW_MIN_INTERVAL_S", 2.0),
            timeout_s=_env_float("TNW_TIMEOUT_S", 45.0),
            max_attempts=_env_int("TNW_MAX_ATTEMPTS", 4),
            respect_robots=os.environ.get("TNW_RESPECT_ROBOTS", "1") not in ("0", "false", "no"),
            max_detail_pages=_env_int("TNW_MAX_DETAIL_PAGES", 25),
            max_documents=_env_int("TNW_MAX_DOCUMENTS", 6),
            max_pdf_pages=_env_int("TNW_MAX_PDF_PAGES", 400),
            max_body_chars=_env_int("TNW_MAX_BODY_CHARS", 20_000),
            archive_backend=os.environ.get("TNW_ARCHIVE_BACKEND", "local"),
            s3_bucket=os.environ.get("TNW_ARCHIVE_S3_BUCKET", ""),
            s3_prefix=os.environ.get("TNW_ARCHIVE_S3_PREFIX", "archive"),
            s3_endpoint_url=os.environ.get("TNW_ARCHIVE_S3_ENDPOINT") or None,
        )
        return replace(config, **overrides) if overrides else config

    def archive_writer(self) -> ArchiveWriter:
        if self.archive_backend == "s3":
            if not self.s3_bucket:
                raise ValueError("TNW_ARCHIVE_S3_BUCKET must be set for the s3 backend")
            return S3ArchiveWriter(
                self.s3_bucket, prefix=self.s3_prefix, endpoint_url=self.s3_endpoint_url
            )
        if self.archive_backend != "local":
            raise ValueError(f"unknown archive backend: {self.archive_backend!r}")
        return LocalGzipArchiveWriter(self.archive_path)

    def fetcher(self) -> Fetcher:
        return Fetcher(
            contact=self.contact,
            user_agent=self.user_agent,
            min_interval_s=self.min_interval_s,
            timeout_s=self.timeout_s,
            max_attempts=self.max_attempts,
            respect_robots=self.respect_robots,
        )

    def limits(self):
        from adapters.base import Limits

        return Limits(
            max_detail_pages=self.max_detail_pages,
            max_documents=self.max_documents,
            max_pdf_pages=self.max_pdf_pages,
            max_body_chars=self.max_body_chars,
        )
