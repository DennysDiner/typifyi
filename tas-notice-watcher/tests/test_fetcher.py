"""Fetch politeness and failure semantics (§2.3, §5). No network is used."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from conftest import FakeClock

from tnw.fetcher import (
    Fetcher,
    RobotsDisallowed,
    StructuralFetchError,
    TransientFetchError,
)


@dataclass
class FakeResponse:
    status_code: int = 200
    content: bytes = b"body"
    headers: dict = field(default_factory=dict)
    text: str = ""
    url: str = "https://x.tas.gov.au/a"


class FakeSession:
    """Records requests and replays a scripted list of responses per URL."""

    def __init__(self, responses: dict[str, list]):
        self.responses = {url: list(items) for url, items in responses.items()}
        self.requests: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None):
        self.requests.append((url, dict(headers or {})))
        queue = self.responses.get(url)
        if not queue:
            return FakeResponse(status_code=404, content=b"missing", url=url)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


ROBOTS_ALLOW = FakeResponse(status_code=200, text="User-agent: *\nAllow: /\n")


def build(responses, **kwargs):
    clock = FakeClock()
    session = FakeSession(responses)
    fetcher = Fetcher(
        session=session,
        min_interval_s=2.0,
        backoff_base_s=2.0,
        jitter=0.0,
        sleep=clock.sleep,
        clock=clock.monotonic,
        **kwargs,
    )
    return fetcher, session, clock


def test_conditional_get_sends_stored_validators_and_reports_304():
    fetcher, session, _ = build(
        {
            "https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
            "https://x.tas.gov.au/list": [FakeResponse(status_code=304, content=b"", url="https://x.tas.gov.au/list")],
        }
    )
    result = fetcher.get("https://x.tas.gov.au/list", etag='"v1"', last_modified="Mon, 31 Aug 2026 00:00:00 GMT")
    assert result.not_modified and result.status == 304 and result.body == b""
    sent = session.requests[-1][1]
    assert sent["If-None-Match"] == '"v1"'
    assert sent["If-Modified-Since"] == "Mon, 31 Aug 2026 00:00:00 GMT"


def test_user_agent_carries_a_contact_address():
    fetcher, session, _ = build(
        {"https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
         "https://x.tas.gov.au/a": [FakeResponse()]},
        contact="watcher@example.org",
    )
    fetcher.get("https://x.tas.gov.au/a")
    assert "watcher@example.org" in session.requests[-1][1]["User-Agent"]


def test_requests_to_one_host_are_spaced_by_at_least_two_seconds():
    fetcher, _, clock = build(
        {"https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
         "https://x.tas.gov.au/a": [FakeResponse()],
         "https://x.tas.gov.au/b": [FakeResponse()]}
    )
    fetcher.get("https://x.tas.gov.au/a")
    fetcher.get("https://x.tas.gov.au/b")
    assert clock.slept and max(clock.slept) >= 1.9


def test_crawl_delay_is_honoured_when_longer_than_our_minimum():
    fetcher, _, clock = build(
        {
            "https://x.tas.gov.au/robots.txt": [
                FakeResponse(text="User-agent: *\nAllow: /\nCrawl-delay: 9\n")
            ],
            "https://x.tas.gov.au/a": [FakeResponse()],
            "https://x.tas.gov.au/b": [FakeResponse()],
        }
    )
    fetcher.get("https://x.tas.gov.au/a")
    fetcher.get("https://x.tas.gov.au/b")
    assert max(clock.slept) >= 8.9


def test_server_errors_are_retried_with_exponential_backoff():
    fetcher, session, clock = build(
        {
            "https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
            "https://x.tas.gov.au/a": [
                FakeResponse(status_code=503),
                FakeResponse(status_code=503),
                FakeResponse(status_code=200, content=b"ok"),
            ],
        }
    )
    result = fetcher.get("https://x.tas.gov.au/a")
    assert result.status == 200 and result.attempts == 3
    backoffs = [s for s in clock.slept if s in (2.0, 4.0, 8.0)]
    assert backoffs[:2] == [2.0, 4.0]


def test_persistent_server_errors_raise_a_transient_failure():
    fetcher, _, _ = build(
        {"https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
         "https://x.tas.gov.au/a": [FakeResponse(status_code=500)]},
        max_attempts=2,
    )
    with pytest.raises(TransientFetchError):
        fetcher.get("https://x.tas.gov.au/a")


def test_retry_after_is_respected_on_429():
    fetcher, _, clock = build(
        {
            "https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
            "https://x.tas.gov.au/a": [
                FakeResponse(status_code=429, headers={"Retry-After": "15"}),
                FakeResponse(status_code=200),
            ],
        }
    )
    fetcher.get("https://x.tas.gov.au/a")
    assert 15.0 in clock.slept


def test_client_errors_are_structural_and_never_retried():
    fetcher, session, _ = build(
        {"https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
         "https://x.tas.gov.au/a": [FakeResponse(status_code=404)]}
    )
    with pytest.raises(StructuralFetchError) as excinfo:
        fetcher.get("https://x.tas.gov.au/a")
    assert excinfo.value.status == 404
    assert len([r for r in session.requests if r[0].endswith("/a")]) == 1


def test_network_errors_are_retried_then_reported():
    fetcher, _, _ = build(
        {"https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
         "https://x.tas.gov.au/a": [OSError("connection reset")]},
        max_attempts=3,
    )
    with pytest.raises(TransientFetchError):
        fetcher.get("https://x.tas.gov.au/a")


def test_robots_disallow_blocks_the_fetch():
    fetcher, session, _ = build(
        {
            "https://x.tas.gov.au/robots.txt": [
                FakeResponse(text="User-agent: *\nDisallow: /private\n")
            ],
            "https://x.tas.gov.au/private/a": [FakeResponse()],
            "https://x.tas.gov.au/public/a": [FakeResponse()],
        }
    )
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://x.tas.gov.au/private/a")
    assert fetcher.get("https://x.tas.gov.au/public/a").status == 200


def test_unreadable_robots_is_treated_as_disallow():
    """RFC 9309: a 5xx on robots.txt means assume complete disallow."""
    fetcher, _, _ = build(
        {"https://x.tas.gov.au/robots.txt": [FakeResponse(status_code=503)],
         "https://x.tas.gov.au/a": [FakeResponse()]}
    )
    with pytest.raises(RobotsDisallowed):
        fetcher.get("https://x.tas.gov.au/a")


def test_missing_robots_allows_everything():
    fetcher, _, _ = build(
        {"https://x.tas.gov.au/robots.txt": [FakeResponse(status_code=404)],
         "https://x.tas.gov.au/a": [FakeResponse()]}
    )
    assert fetcher.get("https://x.tas.gov.au/a").status == 200


def test_robots_is_fetched_once_per_host():
    fetcher, session, _ = build(
        {"https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
         "https://x.tas.gov.au/a": [FakeResponse()],
         "https://x.tas.gov.au/b": [FakeResponse()]}
    )
    fetcher.get("https://x.tas.gov.au/a")
    fetcher.get("https://x.tas.gov.au/b")
    assert sum(1 for url, _ in session.requests if url.endswith("robots.txt")) == 1


def test_response_text_uses_the_declared_charset():
    fetcher, _, _ = build(
        {
            "https://x.tas.gov.au/robots.txt": [ROBOTS_ALLOW],
            "https://x.tas.gov.au/a": [
                FakeResponse(content="Nyrstar café".encode("latin-1"),
                             headers={"Content-Type": "text/html; charset=latin-1"})
            ],
        }
    )
    assert fetcher.get("https://x.tas.gov.au/a").text() == "Nyrstar café"
