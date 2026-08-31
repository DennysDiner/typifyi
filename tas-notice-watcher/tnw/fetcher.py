"""Polite, conditional HTTP fetching (§2.3).

Rules enforced here:

* conditional GET using stored ``ETag`` / ``Last-Modified``;
* ``robots.txt`` respected, including ``Crawl-delay``;
* a descriptive ``User-Agent`` carrying a contact address;
* at least 2 seconds between requests to the same host;
* exponential backoff on 5xx/429/network errors;
* 4xx treated as a *structural* failure that must alert, not a quiet skip.
"""

from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

import requests

from .timeutil import utcnow_iso

LOG = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "tas-notice-watcher/0.1 (+https://github.com/DennysDiner/typifyi; "
    "public-interest change monitoring; contact: {contact})"
)
DEFAULT_CONTACT = "tas-notice-watcher@example.invalid"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 507, 509})


class FetchError(RuntimeError):
    """Base class for fetch failures."""

    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class StructuralFetchError(FetchError):
    """A 4xx response: the endpoint moved or changed shape. Always alerts (§5)."""


class TransientFetchError(FetchError):
    """5xx or network failure that survived all retries."""


class RobotsDisallowed(FetchError):
    """robots.txt forbids this fetch, or could not be established."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    fetched_at: str
    elapsed_s: float
    not_modified: bool = False
    attempts: int = 1

    @property
    def content_type(self) -> str | None:
        for key, value in self.headers.items():
            if key.lower() == "content-type":
                return value
        return None

    def text(self, default_encoding: str = "utf-8") -> str:
        content_type = self.content_type or ""
        encoding = default_encoding
        if "charset=" in content_type.lower():
            encoding = content_type.lower().split("charset=", 1)[1].split(";")[0].strip()
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode(default_encoding, errors="replace")


@dataclass
class _HostState:
    next_allowed_at: float = 0.0
    robots: urllib.robotparser.RobotFileParser | None = None
    robots_checked: bool = False
    robots_error: str | None = None
    crawl_delay: float | None = None


class Fetcher:
    """A rate-limited, robots-respecting HTTP client.

    Time and sleeping are injected so the whole class is testable offline.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        contact: str = DEFAULT_CONTACT,
        user_agent: str | None = None,
        min_interval_s: float = 2.0,
        timeout_s: float = 45.0,
        max_attempts: int = 4,
        backoff_base_s: float = 2.0,
        backoff_max_s: float = 32.0,
        jitter: float = 0.25,
        respect_robots: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.user_agent = user_agent or DEFAULT_USER_AGENT.format(contact=contact)
        self.min_interval_s = min_interval_s
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.backoff_base_s = backoff_base_s
        self.backoff_max_s = backoff_max_s
        self.jitter = jitter
        self.respect_robots = respect_robots
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.Random(0)
        self._hosts: dict[str, _HostState] = {}
        self.request_count = 0
        self.bytes_downloaded = 0

    # -- politeness ---------------------------------------------------------

    def _host_state(self, url: str) -> tuple[str, _HostState]:
        host = urlsplit(url).netloc.lower()
        return host, self._hosts.setdefault(host, _HostState())

    def _wait_turn(self, state: _HostState) -> None:
        interval = max(self.min_interval_s, state.crawl_delay or 0.0)
        now = self._clock()
        if now < state.next_allowed_at:
            self._sleep(state.next_allowed_at - now)
        state.next_allowed_at = self._clock() + interval

    def _load_robots(self, url: str, state: _HostState) -> None:
        if state.robots_checked:
            return
        state.robots_checked = True
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            response = self.session.get(
                robots_url,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_s,
            )
        except Exception as exc:  # network failure
            state.robots_error = f"robots.txt unreachable: {exc}"
            return
        parser = urllib.robotparser.RobotFileParser()
        if response.status_code >= 500:
            # RFC 9309: a server error means "assume complete disallow".
            state.robots_error = f"robots.txt returned {response.status_code}"
            return
        if 400 <= response.status_code < 500:
            parser.parse([])  # no robots.txt: everything allowed
        else:
            parser.parse(response.text.splitlines())
            delay = parser.crawl_delay(self.user_agent)
            if delay:
                state.crawl_delay = float(delay)
        state.robots = parser

    def _check_robots(self, url: str, state: _HostState) -> None:
        if not self.respect_robots:
            return
        self._load_robots(url, state)
        if state.robots_error:
            raise RobotsDisallowed(state.robots_error, url=url)
        if state.robots is not None and not state.robots.can_fetch(self.user_agent, url):
            raise RobotsDisallowed("robots.txt disallows this URL", url=url)

    # -- fetching -----------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        accept: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> FetchResult:
        host, state = self._host_state(url)
        self._check_robots(url, state)

        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        if accept:
            headers["Accept"] = accept
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if extra_headers:
            headers.update(extra_headers)

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._wait_turn(state)
            started = self._clock()
            try:
                response = self.session.get(url, headers=headers, timeout=self.timeout_s)
            except Exception as exc:
                last_error = exc
                LOG.warning("fetch error %s (attempt %s/%s): %s", url, attempt, self.max_attempts, exc)
                if attempt == self.max_attempts:
                    break
                self._backoff(attempt, None)
                continue

            elapsed = self._clock() - started
            status = response.status_code
            self.request_count += 1
            body = b"" if status == 304 else (response.content or b"")
            self.bytes_downloaded += len(body)

            if status in RETRYABLE_STATUS:
                last_error = TransientFetchError(
                    f"HTTP {status} from {url}", url=url, status=status
                )
                LOG.warning("retryable HTTP %s for %s (attempt %s/%s)", status, url, attempt, self.max_attempts)
                if attempt == self.max_attempts:
                    break
                self._backoff(attempt, response.headers.get("Retry-After"))
                continue

            if 400 <= status < 500:
                raise StructuralFetchError(
                    f"HTTP {status} from {url}: the endpoint moved or changed shape",
                    url=url,
                    status=status,
                )

            return FetchResult(
                url=url,
                final_url=str(response.url),
                status=status,
                headers={str(k): str(v) for k, v in response.headers.items()},
                body=body,
                fetched_at=utcnow_iso(),
                elapsed_s=elapsed,
                not_modified=(status == 304),
                attempts=attempt,
            )

        message = f"giving up on {url} after {self.max_attempts} attempts: {last_error}"
        status = getattr(last_error, "status", None)
        raise TransientFetchError(message, url=url, status=status)

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = min(self.backoff_base_s * (2 ** (attempt - 1)), self.backoff_max_s)
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), self.backoff_max_s))
            except ValueError:
                pass
        if self.jitter:
            delay += self._rng.uniform(0, self.jitter * delay)
        self._sleep(delay)
