"""Ingestion: RSS feeds, Google News RSS queries, and page-diff monitors.

Everything lands in the items table; ranking happens at insert time and
filtering happens only at the digest level.
"""

import html as html_mod
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus, urljoin, urlsplit

from tasmon import db
from tasmon.config import Config
from tasmon.extract import extract_text, extract_title
from tasmon.http import Fetcher, RobotsDisallowed
from tasmon.score import Scorer, find_near_duplicate


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def google_news_url(query: str) -> str:
    return ("https://news.google.com/rss/search?q=" + quote_plus(query)
            + "&hl=en-AU&gl=AU&ceid=AU:en")


class Ingestor:
    def __init__(self, cfg: Config, conn):
        self.cfg = cfg
        self.conn = conn
        self.fetcher = Fetcher(cfg.user_agent, cfg.timeout, cfg.respect_robots)
        self.scorer = Scorer(cfg)
        self.new_items: list[int] = []  # row ids inserted this run

    # ------------------------------------------------------------------
    def run_schedule(self, schedule: str) -> list[int]:
        for source in self.cfg.sources_for_schedule(schedule):
            self.run_source(source)
        return self.new_items

    def run_source(self, source: dict):
        stype = source.get("type", "rss")
        try:
            if stype == "rss":
                self._ingest_feed(source, source["url"], check_robots=False)
            elif stype == "google_news":
                self._ingest_feed(source, google_news_url(source["query"]),
                                  check_robots=False)
            elif stype == "page_diff":
                self._ingest_page_diff(source)
            else:
                raise ValueError(f"unknown source type: {stype}")
            db.log_fetch(self.conn, source["id"], now_iso(), ok=True)
        except RobotsDisallowed as e:
            db.log_fetch(self.conn, source["id"], now_iso(), ok=False, error=str(e))
        except Exception as e:  # noqa: BLE001 — feed rot must never kill the run
            db.log_fetch(self.conn, source["id"], now_iso(), ok=False,
                         error=f"{type(e).__name__}: {e}"[:500])

    # ------------------------------------------------------------------
    def _ingest_feed(self, source: dict, feed_url: str, check_robots: bool):
        import feedparser
        resp = self.fetcher.get(feed_url, check_robots=check_robots)
        parsed = feedparser.parse(resp.content)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(f"unparseable feed: {parsed.bozo_exception}")
        require = source.get("require_terms")
        require_res = None
        if require:
            from tasmon.config import compile_terms
            require_res = compile_terms(require)
        for entry in parsed.entries[: source.get("max_entries", 100)]:
            link = entry.get("link")
            title = html_mod.unescape(entry.get("title", "")).strip()
            if not link or not title:
                continue
            summary = re.sub(r"<[^>]+>", " ", entry.get("summary", "") or "")
            if require_res and not any(
                    p.search(title + " " + summary) for p in require_res):
                continue
            published = None
            for key in ("published_parsed", "updated_parsed"):
                if entry.get(key):
                    published = datetime(*entry[key][:6], tzinfo=timezone.utc)\
                        .isoformat(timespec="seconds")
                    break
            self._store(source, url=link, title=title, published_at=published,
                        prefetched_text=summary.strip() or None)

    # ------------------------------------------------------------------
    _LINK_RE = re.compile(
        r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL)

    def _ingest_page_diff(self, source: dict):
        """Hash a listing page, extract links, treat unseen links as new items."""
        resp = self.fetcher.get(source["url"])
        content = resp.text
        import hashlib
        content_hash = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
        prev = self.conn.execute(
            "SELECT content_hash FROM page_snapshots WHERE source_id = ?",
            (source["id"],)).fetchone()
        first_run = prev is None
        self.conn.execute(
            "INSERT INTO page_snapshots (source_id, content_hash, fetched_at) "
            "VALUES (?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
            "content_hash = excluded.content_hash, fetched_at = excluded.fetched_at",
            (source["id"], content_hash, now_iso()))
        if prev and prev["content_hash"] == content_hash:
            self.conn.commit()
            return  # page unchanged, nothing to diff

        include = source.get("link_include", [])
        exclude = source.get("link_exclude", [])
        page_host = urlsplit(source["url"]).netloc
        seen_this_page = set()
        for match in self._LINK_RE.finditer(content):
            href = urljoin(source["url"], match.group(1).strip())
            if href in seen_this_page:
                continue
            seen_this_page.add(href)
            if urlsplit(href).scheme not in ("http", "https"):
                continue
            if source.get("same_host_only", True) and urlsplit(href).netloc != page_host:
                continue
            if include and not any(pat in href for pat in include):
                continue
            if exclude and any(pat in href for pat in exclude):
                continue
            text = re.sub(r"<[^>]+>", " ", match.group(2))
            text = html_mod.unescape(re.sub(r"\s+", " ", text)).strip()
            known = self.conn.execute(
                "SELECT 1 FROM page_links WHERE source_id = ? AND url = ?",
                (source["id"], href)).fetchone()
            if known:
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO page_links (source_id, url, first_seen) "
                "VALUES (?, ?, ?)", (source["id"], href, now_iso()))
            # First run just baselines the page — don't flood the digest with
            # the site's entire back catalogue.
            if not first_run:
                self._store(source, url=href, title=text or href, published_at=None)
        self.conn.commit()

    # ------------------------------------------------------------------
    def _store(self, source: dict, url: str, title: str,
               published_at: str | None, prefetched_text: str | None = None):
        if self.conn.execute("SELECT 1 FROM items WHERE url_hash = ?",
                             (db.url_hash(url),)).fetchone():
            return

        fulltext = prefetched_text
        if source.get("fulltext") and source.get("tier", 2) == 1:
            fulltext = self._fetch_fulltext(url, source) or prefetched_text
            # Page-diff links often have poor anchor text; prefer the page title.
            if getattr(self, "_last_title", None) and (not title or title == url):
                title = self._last_title

        score, wl_hits, sal_hits = self.scorer.score(
            title, fulltext, source.get("tier", 2), published_at)
        dup_of = find_near_duplicate(self.conn, title,
                                     self.cfg.near_duplicate_threshold)
        row_id = db.insert_item(
            self.conn,
            url=url, title=title,
            source_id=source["id"], source_name=source.get("name", source["id"]),
            tier=source.get("tier", 2), category=source.get("category", "news"),
            paywalled=1 if source.get("paywalled") else 0,
            published_at=published_at, fetched_at=now_iso(),
            fulltext=fulltext, score=score,
            watchlist_hits=wl_hits, salience_hits=sal_hits,
            duplicate_of=dup_of,
        )
        if row_id and not dup_of:
            self.new_items.append(row_id)

    def _fetch_fulltext(self, url: str, source: dict) -> str | None:
        self._last_title = None
        try:
            resp = self.fetcher.get(url)
        except (RobotsDisallowed, Exception):
            return None
        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype and "xml" not in ctype:
            return None  # PDFs etc: keep link only
        self._last_title = extract_title(resp.text)
        return extract_text(resp.text, url=url)
