"""Polite HTTP fetching: honest user-agent, robots.txt, retry with backoff."""

import time
import urllib.robotparser
from urllib.parse import urlsplit

import requests


class Fetcher:
    def __init__(self, user_agent: str, timeout: int = 30, respect_robots: bool = True):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.user_agent = user_agent
        self.timeout = timeout
        self.respect_robots = respect_robots
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_request_at: dict[str, float] = {}
        self.min_interval = 1.5  # seconds between requests to the same host

    def _robots_allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        host = urlsplit(url).netloc
        rp = self._robots_cache.get(host, "unset")
        if rp == "unset":
            rp = urllib.robotparser.RobotFileParser()
            try:
                resp = self.session.get(
                    f"{urlsplit(url).scheme}://{host}/robots.txt", timeout=self.timeout)
                if resp.status_code >= 400:
                    rp.parse([])  # no robots.txt -> everything allowed
                else:
                    rp.parse(resp.text.splitlines())
            except requests.RequestException:
                rp = None  # robots unreachable: allow, host fetch will fail anyway
            self._robots_cache[host] = rp
        if rp is None:
            return True
        return rp.can_fetch(self.user_agent, url)

    def _throttle(self, url: str):
        host = urlsplit(url).netloc
        last = self._last_request_at.get(host, 0)
        wait = self.min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at[host] = time.monotonic()

    def get(self, url: str, check_robots: bool = True, retries: int = 2):
        """Fetch a URL. Returns requests.Response.

        Raises RobotsDisallowed or requests.RequestException on failure.
        Set check_robots=False for declared feed endpoints (RSS/Atom URLs
        the publisher exposes for syndication).
        """
        if check_robots and not self._robots_allowed(url):
            raise RobotsDisallowed(url)
        delay = 2
        for attempt in range(retries + 1):
            self._throttle(url)
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException:
                if attempt >= retries:
                    raise
                time.sleep(delay)
                delay *= 2


class RobotsDisallowed(Exception):
    def __init__(self, url):
        super().__init__(f"robots.txt disallows fetching {url}")
