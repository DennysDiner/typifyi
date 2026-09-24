"""Adapter interface.

An adapter turns the bytes of a polled listing (a disclosure log page, a PDF index, ...) into a list of
ListedItem. It is pure: no network. Adapters that need to follow a per-release page implement
`expand()` and are given a fetch callable by the monitor.

Adapters are selected by `disclosure_log_format` in the registry, or by an explicit `adapter:` override
in the authority record (bespoke adapters live in this package and register themselves via
`@register("name")`).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

from dateutil import parser as dateparser

DOC_EXTS = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv", ".zip", ".txt", ".rtf")


@dataclass
class ListedItem:
    external_key: str
    title: str
    url: str | None = None                 # canonical link for the entry (release page or document)
    reference: str | None = None
    published_date: str | None = None      # ISO date
    decision_date: str | None = None
    fields: dict = field(default_factory=dict)
    document_urls: list[str] = field(default_factory=list)
    page_url: str | None = None            # for per_release_pages: page to expand

    def fingerprint(self) -> str:
        payload = {
            "title": norm_ws(self.title),
            "url": self.url,
            "reference": self.reference,
            "published_date": self.published_date,
            "decision_date": self.decision_date,
            "fields": {k: norm_ws(str(v)) for k, v in sorted(self.fields.items()) if v not in (None, "")},
            "document_urls": sorted(self.document_urls),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class FetchFn(Protocol):
    def __call__(self, url: str) -> bytes: ...


class Adapter:
    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""

    def parse(self, body: bytes, base_url: str, config: dict) -> list[ListedItem]:
        raise NotImplementedError

    def next_page(self, body: bytes, base_url: str, config: dict) -> str | None:
        """Return the URL of the next listing page, if the log is paginated."""
        return None

    def expand(self, item: ListedItem, fetch: FetchFn, config: dict) -> ListedItem:
        """Follow item.page_url (a per-release page) and collect document links from it. Generic default
        used by every adapter; config: doc_link_selector, page_title_selector, page_body_selector."""
        if not item.page_url:
            return item
        from bs4 import BeautifulSoup
        body = fetch(item.page_url)
        soup = BeautifulSoup(body, "lxml")
        urls: list[str] = []
        for a in soup.select(config.get("doc_link_selector", "a[href]")):
            if not a.has_attr("href"):
                continue
            u = canon_url(a["href"], item.page_url)
            if is_doc_url(u) and u not in urls:
                urls.append(u)
        item.document_urls = urls
        if config.get("page_title_selector"):
            t = soup.select_one(config["page_title_selector"])
            if t:
                item.title = norm_ws(t.get_text(" ", strip=True)) or item.title
        main = soup.select_one(config.get("page_body_selector", "main")) or soup.body or soup
        item.fields["page_text"] = norm_ws(main.get_text(" ", strip=True))[:4000]
        if not item.published_date:
            item.published_date = find_date(item.fields["page_text"])
        return item


REGISTRY: dict[str, type[Adapter]] = {}


def register(name: str) -> Callable[[type[Adapter]], type[Adapter]]:
    def deco(cls: type[Adapter]) -> type[Adapter]:
        cls.name = name
        REGISTRY[name] = cls
        return cls
    return deco


def get_adapter(name: str) -> Adapter:
    # ensure built-ins are imported
    from . import (  # noqa: F401
        annual_report,
        auto,
        hansard,
        html_list,
        html_table,
        ombudsman_decisions,
        pdf_index,
        per_release_pages,
    )
    try:
        from . import bespoke  # noqa: F401  (optional package of site-specific adapters)
    except ImportError:
        pass
    if name not in REGISTRY:
        raise KeyError(f"unknown adapter {name!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[name]()


# ---- helpers shared by adapters -------------------------------------------------------------------
_WS = re.compile(r"\s+")


def norm_ws(s: str | None) -> str:
    return _WS.sub(" ", (s or "")).strip()


def canon_url(url: str, base: str) -> str:
    u = urljoin(base, url.strip())
    parts = urlsplit(u)
    if parts.scheme.lower() not in ("http", "https"):
        return ""  # javascript:, mailto:, data: are never links we follow or render
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


_DOC_PATH_HINTS = ("/__data/assets/", "/download", "/getmedia/", "/documentcenter/view/", "/sites/default/files/", "/getattachment/")


def is_doc_url(url: str) -> bool:
    parts = urlsplit(url)
    path, query = parts.path.lower(), parts.query.lower()
    if parts.scheme not in ("http", "https"):
        return False
    return (path.endswith(DOC_EXTS) or any(h in path for h in _DOC_PATH_HINTS) or "download.aspx" in path
            or ("drive.google.com" in parts.netloc and "/file/" in path) or ("1drv.ms" in parts.netloc)
            or ("attachment" in query and "id=" in query))


_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
    re.compile(r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b", re.IGNORECASE),
    re.compile(r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
]


def parse_date(s: str | None) -> str | None:
    """Parse an Australian-style date (day first) to ISO. Returns None if not parseable."""
    if not s:
        return None
    s = norm_ws(s)
    try:
        d = dateparser.parse(s, dayfirst=True, fuzzy=True, default=datetime(1900, 1, 1))  # noqa: DTZ001
        if d.year < 1990:
            return None
        return d.date().isoformat()
    except (ValueError, OverflowError):
        return None


def find_date(s: str | None) -> str | None:
    if not s:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(s)
        if m:
            iso = parse_date(m.group(1))
            if iso:
                return iso
    return None


def stable_key(*parts: str | None) -> str:
    raw = "|".join(norm_ws(p or "").lower() for p in parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# A reference must carry a prefix (RTI/FOI/Ref/No) or be a financial-year style token (2024-25/031, 2025/031).
# Plain dates (12/05/2025, 12-05-2025) are explicitly rejected: mistaking a date for a reference merged
# distinct same-day releases into one item (audit finding 32).
_REF_PAT = re.compile(r"\b((?:RTI|FOI|Ref(?:erence)?\.?|No\.?)\s*[:#-]?\s*[A-Z0-9][\w/-]{1,24}|(?:20\d{2}[-/]\d{2,4}/\d{1,4}))\b", re.IGNORECASE)
_DATE_SHAPE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$|^\d{4}[/-]\d{1,2}[/-]\d{1,2}$")


def find_reference(*texts: str | None) -> str | None:
    for t in texts:
        if not t:
            continue
        for m in _REF_PAT.finditer(t):
            cand = m.group(1).strip().rstrip(".,;:")
            core = re.sub(r"^(RTI|FOI|Ref(?:erence)?\.?|No\.?)\s*[:#-]?\s*", "", cand, flags=re.IGNORECASE)
            if _DATE_SHAPE.match(core) or not any(ch.isdigit() for ch in core):
                continue
            # keep RTI/FOI prefixes (they are part of the number); drop "Reference"/"No" words
            return re.sub(r"^(Ref(?:erence)?\.?|No\.?)\s*[:#-]?\s*", "", cand, flags=re.IGNORECASE)
    return None


_NEXT_TEXT = re.compile(r"^(next|next page|older|more|›|»|>|>>)\s*$", re.IGNORECASE)


def find_next_page(soup, base_url: str) -> str | None:
    """Heuristic pagination: rel=next, common pager classes, or link text like Next / › / »."""
    a = soup.select_one('a[rel~="next"], link[rel~="next"], a.next, li.next > a, a.pagination-next, a[aria-label="Next"], a[aria-label="Next page"]')
    if a is not None and a.has_attr("href"):
        u = canon_url(a["href"], base_url)
        if u and u != base_url:
            return u
    for a in soup.find_all("a", href=True):
        if _NEXT_TEXT.match(norm_ws(a.get_text(" ", strip=True)) or ""):
            u = canon_url(a["href"], base_url)
            if u and u != base_url:
                return u
    return None


def dedupe(items: Iterable[ListedItem]) -> list[ListedItem]:
    seen: dict[str, ListedItem] = {}
    for it in items:
        if it.external_key in seen:
            # merge document urls
            prev = seen[it.external_key]
            for u in it.document_urls:
                if u not in prev.document_urls:
                    prev.document_urls.append(u)
        else:
            seen[it.external_key] = it
    return list(seen.values())
