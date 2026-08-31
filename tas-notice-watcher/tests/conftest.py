"""Shared test helpers. No test in this suite touches the network."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

from tnw.config import Config  # noqa: E402
from tnw.fetcher import FetchResult, StructuralFetchError  # noqa: E402
from tnw.timeutil import utcnow_iso  # noqa: E402


def fixture_bytes(*parts: str) -> bytes:
    return (FIXTURES.joinpath(*parts)).read_bytes()


def fixture_text(*parts: str) -> str:
    return (FIXTURES.joinpath(*parts)).read_text(encoding="utf-8")


@dataclass
class Route:
    """A canned HTTP response for one URL."""

    body: bytes = b""
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    etag: str | None = None
    last_modified: str | None = None
    error: Exception | None = None

    @classmethod
    def html(cls, *parts: str, **kwargs) -> "Route":
        return cls(body=fixture_bytes(*parts), **kwargs)

    @classmethod
    def pdf(cls, *parts: str, **kwargs) -> "Route":
        return cls(body=fixture_bytes(*parts), content_type="application/pdf", **kwargs)


class FakeFetcher:
    """A Fetcher stand-in driven by a URL → Route table.

    Unknown URLs raise :class:`StructuralFetchError`, mirroring a 404 — so a
    test that mistypes a URL fails loudly instead of silently returning nothing.
    """

    def __init__(self, routes: dict[str, Route] | None = None, *, now: str | None = None) -> None:
        self.routes: dict[str, Route] = dict(routes or {})
        self.calls: list[tuple[str, dict]] = []
        self.request_count = 0
        self.bytes_downloaded = 0
        self.now = now or utcnow_iso()

    def add(self, url: str, route: Route) -> None:
        self.routes[url] = route

    def get(self, url, *, etag=None, last_modified=None, accept=None, extra_headers=None):
        self.calls.append((url, {"etag": etag, "last_modified": last_modified, "accept": accept}))
        route = self.routes.get(url)
        if route is None:
            raise StructuralFetchError(f"HTTP 404 from {url} (no route registered)", url=url, status=404)
        if route.error is not None:
            raise route.error
        self.request_count += 1
        headers = {"Content-Type": route.content_type}
        if route.etag:
            headers["ETag"] = route.etag
        if route.last_modified:
            headers["Last-Modified"] = route.last_modified
        not_modified = bool(route.etag and etag == route.etag) or bool(
            route.last_modified and last_modified == route.last_modified
        )
        body = b"" if not_modified else route.body
        self.bytes_downloaded += len(body)
        return FetchResult(
            url=url,
            final_url=url,
            status=304 if not_modified else route.status,
            headers=headers,
            body=body,
            fetched_at=self.now,
            elapsed_s=0.01,
            not_modified=not_modified,
        )


@dataclass
class FakeClock:
    """Monotonic clock and sleep recorder for the fetcher's politeness rules."""

    t: float = 0.0
    slept: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds

    def monotonic(self) -> float:
        self.t += 0.001
        return self.t


@pytest.fixture
def project(tmp_path: Path) -> Config:
    """A throwaway project root with the real watchlist."""
    (tmp_path / "state").mkdir()
    (tmp_path / "records").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "watchlist.yml").write_text(
        (ROOT / "watchlist.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return Config.from_env(tmp_path)


@pytest.fixture
def now() -> str:
    return "2026-08-31T21:05:00Z"
