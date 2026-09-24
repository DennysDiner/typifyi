import pytest

from rti_tracker.fetch import Blocked


def test_conditional_get_and_archive(fetcher, site, conn):
    site.set("/log", "<html>v1</html>")
    r1 = fetcher.get("https://example.tas.gov.au/log", kind="listing")
    assert r1.status == 200 and r1.capture is not None and r1.etag
    r2 = fetcher.get("https://example.tas.gov.au/log", etag=r1.etag, kind="listing")
    assert r2.not_modified and r2.capture is None
    assert conn.execute("SELECT count(*) FROM fetches").fetchone()[0] == 2
    assert conn.execute("SELECT not_modified FROM fetches ORDER BY id DESC LIMIT 1").fetchone()[0] == 1
    # user agent sent, robots fetched first
    assert site.requests[0].url.path == "/robots.txt"
    assert "tas-rti-tracker-test" in site.requests[1].headers["user-agent"]


def test_robots_disallow_is_blocked_not_evaded(fetcher, site, conn):
    site.set("/private/log", "<html>secret</html>")
    with pytest.raises(Blocked):
        fetcher.get("https://example.tas.gov.au/private/log")
    assert not any(r.url.path == "/private/log" for r in site.requests)
    assert "blocked" in conn.execute("SELECT error FROM fetches").fetchone()[0]


def test_403_is_blocked(fetcher, site):
    site.set("/log", "forbidden", status=403)
    with pytest.raises(Blocked):
        fetcher.get("https://example.tas.gov.au/log")


def test_5xx_raises_and_backs_off(fetcher, site):
    from rti_tracker.fetch import FetchError
    site.set("/log", "boom", status=503)
    with pytest.raises(FetchError):
        fetcher.get("https://example.tas.gov.au/log")
    hs = fetcher._host("https://example.tas.gov.au/log")
    assert hs.failures == 1 and hs.backoff_until > 0


def test_404_is_an_error_not_an_empty_success(fetcher, site):
    from rti_tracker.fetch import FetchError
    site.set("/gone", "<html>nav page</html>", status=404)
    with pytest.raises(FetchError):
        fetcher.get("https://example.tas.gov.au/gone")


def test_robots_5xx_means_disallow(fetcher, site):
    site.set("/log", "<html>ok</html>")
    site.robots = None  # handler returns 200 text; emulate 5xx by overriding

    def handler(request):
        import httpx
        if request.url.path == "/robots.txt":
            return httpx.Response(503, text="down")
        return httpx.Response(200, text="<html>ok</html>")
    import httpx
    fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(Blocked):
        fetcher.get("https://example.tas.gov.au/log")
