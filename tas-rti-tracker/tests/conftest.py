from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "synthetic"))
FIX = ROOT / "tests" / "fixtures" / "synthetic"

from rti_tracker import db as dbm
from rti_tracker.archive import Archive
from rti_tracker.fetch import Fetcher


@pytest.fixture
def conn(tmp_path):
    c = dbm.connect(tmp_path / "t.db")
    dbm.migrate(c)
    return c


@pytest.fixture
def archive(conn, tmp_path):
    return Archive(conn, tmp_path / "archive")


def fixture_bytes(name: str) -> bytes:
    return (FIX / name).read_bytes()


class FakeSite:
    """Dict-backed fake web: path -> (status, headers, body). Records requests. Supports ETag/304."""

    def __init__(self, base="https://example.tas.gov.au"):
        self.base = base
        self.pages: dict[str, tuple[int, dict, bytes]] = {}
        self.requests: list[httpx.Request] = []
        self.robots = "User-agent: *\nDisallow: /private/\n"

    def set(self, path: str, body: bytes | str, status=200, content_type="text/html", etag=True):
        if isinstance(body, str):
            body = body.encode()
        import hashlib
        h = {"content-type": content_type}
        if etag:
            h["etag"] = '"' + hashlib.md5(body).hexdigest() + '"'
        self.pages[path] = (status, h, body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path + (("?" + request.url.query.decode()) if request.url.query else "")
        if path == "/robots.txt":
            return httpx.Response(200, text=self.robots)
        if path not in self.pages:
            return httpx.Response(404, text="nope")
        status, headers, body = self.pages[path]
        if headers.get("etag") and request.headers.get("if-none-match") == headers["etag"]:
            return httpx.Response(304, headers=headers)
        return httpx.Response(status, headers=headers, content=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), base_url=self.base, follow_redirects=True)


@pytest.fixture
def site():
    return FakeSite()


@pytest.fixture
def fetcher(conn, archive, site):
    return Fetcher(conn, archive, "tas-rti-tracker-test/0.1 (+test@example.org)", min_interval=0, client=site.client(), sleep=lambda s: None)
