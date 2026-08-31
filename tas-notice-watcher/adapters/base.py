"""The adapter interface.

Every source is reduced to the same shape: fetch, archive the raw bytes,
extract a list of :class:`~tnw.models.Item` records, and declare what "healthy"
looks like so that failure detection has something to check against.

Adapters never invent data. If a field is not stated by the source it stays
null and the item is flagged; if the page yields nothing, the adapter raises
:class:`AdapterParseError` rather than returning an empty list, because an empty
list is indistinguishable from a quiet week and would fail silently (§5).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from tnw.archive import ArchiveRef, ArchiveWriter
from tnw.fetcher import FetchError, FetchResult, Fetcher
from tnw.heartbeat import Expectation
from tnw.hashing import content_hash
from tnw.models import Item
from tnw.normalise import canonical_url
from tnw.state import ItemState, SourceState
from tnw.timeutil import utcnow_iso


class AdapterError(RuntimeError):
    """A failure inside an adapter that must alert."""


class AdapterParseError(AdapterError):
    """The page was fetched but could not be parsed into items."""


def reraise_fetch_failure(source: str, failures: list[tuple[str, Exception]]) -> None:
    """Re-raise a transport failure with its own type, if that is what happened.

    Triage depends on the failure kind: "robots.txt now disallows this" and "the
    page structure changed" call for completely different responses, so a run
    where *every* candidate failed to fetch must not be reported as a parse
    failure.
    """
    if not failures or not all(isinstance(exc, FetchError) for _url, exc in failures):
        return
    first = failures[0][1]
    detail = "; ".join(f"{url}: {type(exc).__name__}: {exc}" for url, exc in failures)
    raise type(first)(
        f"no candidate endpoint could be fetched for {source}: {detail}",
        url=getattr(first, "url", ""),
        status=getattr(first, "status", None),
    )


@dataclass
class Limits:
    """Per-run budgets, so a single job stays inside the Actions time budget."""

    max_detail_pages: int = 25
    max_documents: int = 6
    max_pdf_pages: int = 400
    max_body_chars: int = 20_000


@dataclass
class AdapterContext:
    fetcher: Fetcher
    archive: ArchiveWriter
    state: SourceState
    now: str = field(default_factory=utcnow_iso)
    limits: Limits = field(default_factory=Limits)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("tnw.adapter"))


@dataclass
class AdapterResult:
    items: list[Item] = field(default_factory=list)
    page_bytes: int = 0
    endpoint: str | None = None
    listing_unchanged: bool = False
    # item id -> hash of its listing row, persisted into state by the runner.
    listing_hashes: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Adapter(ABC):
    """One source."""

    name: str = ""
    label: str = ""
    expected_interval_hours: float = 24.0
    grace_hours: float = 24.0
    min_expected_items: int = 1
    supports_removals: bool = False
    # Candidate listing URLs, tried in order. The first that yields items wins
    # and is recorded in state, so a site restructure shows up in the diff of
    # the state file rather than as a silent switch.
    listing_urls: tuple[str, ...] = ()

    @property
    def expectation(self) -> Expectation:
        return Expectation(
            source=self.name,
            expected_interval_hours=self.expected_interval_hours,
            grace_hours=self.grace_hours,
            min_expected_items=self.min_expected_items,
            description=self.label,
        )

    @abstractmethod
    def collect(self, ctx: AdapterContext) -> AdapterResult:
        """Fetch, archive and extract this source's current item list."""

    def discover(self, ctx: AdapterContext) -> dict[str, Any]:
        """Probe the source and report what is actually there.

        Used by ``tnw discover`` to confirm endpoints, formats and update
        patterns before any selector is trusted (§3).
        """
        findings: dict[str, Any] = {"source": self.name, "candidates": []}
        for url in self.candidate_urls(ctx):
            entry: dict[str, Any] = {"url": url}
            try:
                result = ctx.fetcher.get(url)
                entry.update(
                    status=result.status,
                    content_type=result.content_type,
                    bytes=len(result.body),
                    final_url=result.final_url,
                    etag=result.headers.get("ETag"),
                    last_modified=result.headers.get("Last-Modified"),
                )
                entry.update(self.probe(result))
            except Exception as exc:  # discovery reports failures, never raises
                entry.update(error=f"{type(exc).__name__}: {exc}")
            findings["candidates"].append(entry)
        return findings

    def candidate_urls(self, ctx: AdapterContext) -> list[str]:
        return list(self.listing_urls)

    def probe(self, result: FetchResult) -> dict[str, Any]:
        """Adapter-specific discovery detail for one fetched candidate."""
        return {}

    # -- shared helpers -----------------------------------------------------

    def fetch_and_archive(
        self,
        ctx: AdapterContext,
        url: str,
        *,
        conditional: bool = True,
        accept: str | None = None,
    ) -> tuple[FetchResult, ArchiveRef | None]:
        """Conditional GET plus archiving of the raw bytes."""
        validator = ctx.state.validator(url) if conditional else None
        result = ctx.fetcher.get(
            url,
            etag=validator.etag if validator else None,
            last_modified=validator.last_modified if validator else None,
            accept=accept,
        )
        if result.not_modified:
            return result, None
        ctx.state.record_validator(url, result.headers)
        ref = ctx.archive.write(
            self.name,
            result.body,
            content_type=result.content_type,
            url=url,
            fetched_at=result.fetched_at,
        )
        return result, ref

    def make_item(
        self,
        *,
        item_id: str,
        title: str,
        url: str,
        published_at: str | None,
        body_text: str,
        fetched_at: str,
        http_status: int | None,
        archive_path: str | None,
        notes: str = "",
        hash_body: str | None = None,
    ) -> Item:
        """Build an item with its content hash over the canonical fields."""
        item = Item(
            id=item_id,
            source=self.name,
            title=title.strip(),
            url=canonical_url(url),
            published_at=published_at,
            body_text=body_text,
            fetched_at=fetched_at,
            http_status=http_status,
            archive_path=archive_path,
            source_notes=notes,
        )
        item.content_hash = content_hash(
            item.canonical_fields(body_text if hash_body is None else hash_body)
        )
        return item

    def item_from_state(
        self,
        *,
        item_id: str,
        previous: ItemState,
        fetched_at: str,
        note: str = "not_modified_304",
    ) -> Item:
        """Re-emit a known item unchanged, e.g. after a 304 on its detail page.

        The previous content hash is reused deliberately: a conditional GET that
        says "not modified" is evidence of no change, and re-hashing an empty
        body would manufacture a false one.
        """
        item = Item(
            id=item_id,
            source=self.name,
            title=previous.title,
            url=previous.url,
            published_at=previous.published_at,
            body_text="",
            content_hash=previous.content_hash,
            fetched_at=fetched_at,
            http_status=304,
            archive_path=previous.archive_path,
            source_notes=note,
        )
        return item
