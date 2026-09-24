"""Polite HTTP client.

- Conditional GETs (ETag / If-Modified-Since) using per-source state stored by the caller.
- Descriptive User-Agent with contact address (RTI_CONTACT_EMAIL).
- robots.txt respected (cached per host); a disallowed URL is reported as Blocked, never evaded.
- Per-host rate limit (min interval between requests) and exponential backoff on 5xx/429/network errors.
- Every attempt is logged to `fetches`; every body is archived via Archive.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

import httpx

from .archive import Archive, Capture
from .db import utcnow


class Blocked(Exception):
    """The source cannot be polled (robots.txt disallow, 403/451, explicit block)."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    not_modified: bool
    body: bytes
    headers: dict[str, str]
    capture: Optional[Capture]
    etag: str | None
    last_modified: str | None
    retrieved_at: str


@dataclass
class HostState:
    last_request_at: float = 0.0
    robots: urllib.robotparser.RobotFileParser | None = None
    robots_checked_at: float = 0.0
    backoff_until: float = 0.0
    failures: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class Fetcher:
    def __init__(
        self,
        conn: sqlite3.Connection,
        archive: Archive,
        user_agent: str,
        *,
        min_interval: float = 2.0,
        timeout: float = 60.0,
        max_bytes: int = 200 * 1024 * 1024,
        respect_robots: bool = True,
        client: httpx.Client | None = None,
        sleep=time.sleep,
    ):
        self.conn = conn
        self.archive = archive
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self._hosts: dict[str, HostState] = {}
        self._sleep = sleep
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "*/*"},
            timeout=timeout,
            follow_redirects=True,
        )

    # -- host politeness ---------------------------------------------------------------------------
    def _host(self, url: str) -> HostState:
        h = urlsplit(url).netloc.lower()
        if h not in self._hosts:
            self._hosts[h] = HostState()
        return self._hosts[h]

    def _robots_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        hs = self._host(url)
        now = time.time()
        if hs.robots is None or now - hs.robots_checked_at > 86400:
            parts = urlsplit(url)
            robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.client.get(robots_url, headers={"User-Agent": self.user_agent})
                if r.status_code >= 400:
                    rp.parse([])  # no robots => allowed
                else:
                    rp.parse(r.text.splitlines())
                    try:
                        self.archive.store(
                            r.content, url=robots_url, content_type=r.headers.get("content-type"),
                            headers=dict(r.headers), http_status=r.status_code, kind="robots",
                        )
                    except Exception:
                        pass
            except httpx.HTTPError:
                rp.parse([])
            hs.robots = rp
            hs.robots_checked_at = now
        assert hs.robots is not None
        # Check both our specific UA token and '*'.
        return hs.robots.can_fetch(self.user_agent.split("/")[0], url) and hs.robots.can_fetch("*", url)

    def _wait_turn(self, url: str) -> None:
        hs = self._host(url)
        with hs.lock:
            now = time.time()
            wait = max(hs.last_request_at + self.min_interval - now, hs.backoff_until - now, 0.0)
            if wait > 0:
                self._sleep(wait)
            hs.last_request_at = time.time()

    def _note_failure(self, url: str) -> None:
        hs = self._host(url)
        hs.failures += 1
        delay = min(300.0, self.min_interval * (2 ** min(hs.failures, 8)))
        hs.backoff_until = time.time() + delay

    def _note_success(self, url: str) -> None:
        self._host(url).failures = 0

    # -- fetch --------------------------------------------------------------------------------------
    def get(
        self,
        url: str,
        *,
        source_id: int | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        kind: str = "document",
        archive: bool = True,
    ) -> FetchResult:
        started = utcnow()
        cur = self.conn.execute(
            "INSERT INTO fetches(source_id,url,started_at) VALUES (?,?,?)", (source_id, url, started)
        )
        fetch_id = cur.lastrowid
        try:
            if not self._robots_allowed(url):
                raise Blocked(f"robots.txt disallows {url}")
            self._wait_turn(url)
            headers: dict[str, str] = {"User-Agent": self.user_agent}
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
            try:
                with self.client.stream("GET", url, headers=headers) as r:
                    status = r.status_code
                    if status == 304:
                        body = b""
                    else:
                        chunks: list[bytes] = []
                        total = 0
                        for chunk in r.iter_bytes():
                            total += len(chunk)
                            if total > self.max_bytes:
                                raise ValueError(f"response exceeds max_bytes ({self.max_bytes})")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                    resp_headers = {k.lower(): v for k, v in r.headers.items()}
                    final_url = str(r.url)
            except httpx.HTTPError as e:
                self._note_failure(url)
                raise
            retrieved_at = utcnow()
            if status in (401, 403, 451):
                self._note_failure(url)
                self.conn.execute(
                    "UPDATE fetches SET finished_at=?, status_code=?, error=? WHERE id=?",
                    (retrieved_at, status, f"HTTP {status}", fetch_id),
                )
                raise Blocked(f"HTTP {status} for {url}")
            if status == 429 or status >= 500:
                self._note_failure(url)
                self.conn.execute(
                    "UPDATE fetches SET finished_at=?, status_code=?, error=? WHERE id=?",
                    (retrieved_at, status, f"HTTP {status}", fetch_id),
                )
                raise httpx.HTTPStatusError(f"HTTP {status}", request=None, response=None)  # type: ignore[arg-type]
            self._note_success(url)
            capture = None
            if status == 200 and archive:
                capture = self.archive.store(
                    body, url=url, final_url=final_url, content_type=resp_headers.get("content-type"),
                    headers=resp_headers, http_status=status, source_id=source_id, kind=kind,
                    retrieved_at=retrieved_at,
                )
            self.conn.execute(
                "UPDATE fetches SET finished_at=?, status_code=?, not_modified=?, bytes=?, capture_id=? WHERE id=?",
                (retrieved_at, status, 1 if status == 304 else 0, len(body), capture.id if capture else None, fetch_id),
            )
            return FetchResult(
                url=url, final_url=final_url, status=status, not_modified=(status == 304), body=body,
                headers=resp_headers, capture=capture, etag=resp_headers.get("etag"),
                last_modified=resp_headers.get("last-modified"), retrieved_at=retrieved_at,
            )
        except Blocked as e:
            self.conn.execute(
                "UPDATE fetches SET finished_at=?, error=? WHERE id=? AND finished_at IS NULL",
                (utcnow(), f"blocked: {e}", fetch_id),
            )
            raise
        except Exception as e:  # network / parse
            self.conn.execute(
                "UPDATE fetches SET finished_at=?, error=? WHERE id=? AND finished_at IS NULL",
                (utcnow(), f"{type(e).__name__}: {e}", fetch_id),
            )
            raise


def http_date(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
