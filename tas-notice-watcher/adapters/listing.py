"""A configurable HTML listing adapter.

The tenders site and the contract disclosure listing are the same shape: a table
or list of rows, each linking to a detail page. Rather than two near-identical
scrapers, both are configurations of this class.

Two properties matter more than elegance here:

* extraction keys on URL shape and labelled text, so a theme change does not
  silently break it;
* every candidate listing URL is tried in order and the one that worked is
  recorded in state, so a site restructure is visible in a state diff instead of
  producing a quiet zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence
from urllib.parse import urljoin

from tnw.fetcher import FetchResult
from tnw.hashing import sha256_text
from tnw.models import NOTE_PUBLISHED_AT_UNSTATED
from tnw.normalise import canonical_url, normalise_text
from tnw.timeutil import parse_stated_date

from .base import Adapter, AdapterContext, AdapterParseError, AdapterResult, reraise_fetch_failure
from .htmlutil import (
    cell_after_header,
    field_block,
    find_links,
    labelled_value,
    parse,
    row_text,
    table_cells,
    value_from_cells,
)

NEXT_LINK_RE = re.compile(r"(?i)(?:^|\b)(next|»|>>)(?:\b|$)")


@dataclass
class FieldSpec:
    """One structured field, extracted from a row or a detail page by label."""

    key: str
    labels: Sequence[str]
    is_date: bool = False


@dataclass
class ListingConfig:
    detail_link_pattern: re.Pattern[str]
    # Tried in order against the detail URL, the link text and then the row
    # text. Order is priority: a route-derived id beats one scraped from text.
    id_patterns: Sequence[re.Pattern[str]] = ()
    fields: Sequence[FieldSpec] = field(default_factory=tuple)
    published_labels: Sequence[str] = ()
    max_list_pages: int = 3
    follow_next: bool = True
    always_fetch_detail: bool = False


class ListingAdapter(Adapter):
    """Base class for HTML listing sources."""

    config: ListingConfig

    # -- discovery ----------------------------------------------------------

    def probe(self, result: FetchResult) -> dict[str, Any]:
        soup = parse(result.text())
        hits = find_links(soup, result.final_url, self.config.detail_link_pattern)
        feed = soup.find("link", attrs={"type": re.compile("rss|atom")})
        return {
            "detail_links": len(hits),
            "sample": [hit.url for hit in hits[:3]],
            "feed_href": feed.get("href") if feed else None,
            "tables": len(soup.find_all("table")),
        }

    # -- collection ---------------------------------------------------------

    def collect(self, ctx: AdapterContext) -> AdapterResult:
        result = AdapterResult()
        errors: list[str] = []
        fetch_failures: list[tuple[str, Exception]] = []
        rows: list[dict[str, Any]] = []
        unchanged_endpoints = 0

        candidates = self.candidate_urls(ctx)
        # Whatever worked last time is tried first: it is the most likely to work
        # again, and it keeps the endpoint stable across runs.
        if ctx.state.endpoint in candidates:
            candidates.remove(ctx.state.endpoint)
            candidates.insert(0, ctx.state.endpoint)

        for index, url in enumerate(candidates):
            try:
                extracted, page_bytes, unchanged = self._walk_listing(ctx, url, result)
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
                fetch_failures.append((url, exc))
                continue
            result.page_bytes += page_bytes
            if unchanged:
                unchanged_endpoints += 1
                # A 304 from the endpoint that worked last time is authoritative:
                # stop, rather than spending requests on the other candidates.
                if index == 0 or url == ctx.state.endpoint:
                    break
                continue
            if extracted:
                result.endpoint = url
                rows = extracted
                break
            errors.append(f"{url}: fetched but no rows matched {self.config.detail_link_pattern.pattern}")

        if not rows and unchanged_endpoints and self.config.always_fetch_detail:
            # The index is unchanged, but for this source the change that matters
            # happens on the detail pages (a client added to a lobbyist's list),
            # which the index cannot show. Re-check them from what we already know.
            rows = self._rows_from_state(ctx)
            if rows:
                result.endpoint = ctx.state.endpoint
                result.notes.append(
                    "listing unchanged (304); detail pages re-checked from stored state"
                )

        if not rows:
            if unchanged_endpoints:
                result.listing_unchanged = True
                result.endpoint = ctx.state.endpoint
                return result
            reraise_fetch_failure(self.name, fetch_failures)
            raise AdapterParseError(
                f"no rows extracted from any candidate listing for {self.name}: "
                + "; ".join(errors or ["no candidate URLs configured"])
            )

        budget = ctx.limits.max_detail_pages
        for row in rows:
            previous = ctx.state.items.get(row["id"])
            needs_detail = (
                self.config.always_fetch_detail
                or previous is None
                or previous.body_pending
                or previous.listing_hash != row["listing_hash"]
            )
            result.listing_hashes[row["id"]] = row["listing_hash"]
            if not needs_detail and previous is not None:
                item = self.item_from_state(
                    item_id=row["id"], previous=previous, fetched_at=ctx.now,
                    note="unchanged_listing_row",
                )
                item.http_status = 200
                result.items.append(item)
                continue
            if budget <= 0:
                result.items.append(self._item_from_row(ctx, row, detail_fetched=False))
                result.warnings.append(
                    f"{row['id']}: detail page not fetched this run (budget "
                    f"{ctx.limits.max_detail_pages})"
                )
                continue
            budget -= 1
            result.items.append(self._item_with_detail(ctx, row, result, previous))

        return result

    def _rows_from_state(self, ctx: AdapterContext) -> list[dict[str, Any]]:
        """Rebuild the row set from state, for a 304 listing on a detail source."""
        rows: list[dict[str, Any]] = []
        for item_id, previous in sorted(ctx.state.items.items()):
            if previous.removed_at or not previous.url:
                continue
            rows.append(
                {
                    "id": item_id,
                    "native_id": item_id.split(":", 1)[-1],
                    "title": previous.title,
                    "url": previous.url,
                    "row_text": "",
                    "fields": {},
                    "cells": {},
                    "published_at": previous.published_at,
                    "listing_hash": previous.listing_hash,
                }
            )
        return rows

    # -- listing walking ----------------------------------------------------

    def _walk_listing(
        self, ctx: AdapterContext, url: str, result: AdapterResult
    ) -> tuple[list[dict[str, Any]], int, bool]:
        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        page_bytes = 0
        current = url
        unchanged = False

        for page_index in range(max(1, self.config.max_list_pages)):
            fetched, _ref = self.fetch_and_archive(ctx, current)
            if fetched.not_modified:
                result.notes.append(f"{current}: 304 not modified")
                unchanged = page_index == 0
                break
            page_bytes += len(fetched.body)
            html = fetched.text()
            for row in self._extract_rows(fetched.final_url, html):
                if row["id"] in seen_ids:
                    continue
                seen_ids.add(row["id"])
                rows.append(row)
            if not self.config.follow_next:
                break
            next_url = self._next_page(fetched.final_url, html)
            if not next_url or next_url == current:
                break
            current = next_url
        return rows, page_bytes, unchanged

    def _next_page(self, base_url: str, html: str) -> str | None:
        soup = parse(html)
        rel_next = soup.find("a", rel=lambda value: value and "next" in value)
        if rel_next and rel_next.get("href"):
            return canonical_url(urljoin(base_url, rel_next["href"]))
        for anchor in soup.find_all("a", href=True):
            text = " ".join(anchor.get_text(" ").split())
            if NEXT_LINK_RE.fullmatch(text.strip()):
                return canonical_url(urljoin(base_url, anchor["href"]))
        return None

    def _extract_rows(self, base_url: str, html: str) -> list[dict[str, Any]]:
        soup = parse(html)
        rows: list[dict[str, Any]] = []
        for hit in find_links(soup, base_url, self.config.detail_link_pattern):
            container = hit.row
            text = row_text(container)
            cells = table_cells(container)
            native_id = self._native_id(hit.url, hit.text, text)
            title = " ".join(hit.text.split()) or native_id
            fields = self._extract_fields(text, None, cells)
            published_at = self._published_at(text, None, cells)
            rows.append(
                {
                    "id": f"{self.name}:{native_id}",
                    "native_id": native_id,
                    "title": title,
                    "url": hit.url,
                    "row_text": text,
                    "fields": fields,
                    "cells": cells,
                    "published_at": published_at,
                    "listing_hash": sha256_text(f"{hit.url}\n{title}\n{text}"),
                }
            )
        return rows

    def _native_id(self, url: str, link_text: str, row: str) -> str:
        for pattern in self.config.id_patterns:
            for haystack in (url, link_text, row):
                match = pattern.search(haystack or "")
                if not match:
                    continue
                groups = match.groupdict()
                value = groups.get("id") or (match.group(1) if match.groups() else None)
                if value:
                    return re.sub(r"\s+", "", value)
        # No native identifier: fall back to the URL, which is at least stable.
        return f"url:{sha256_text(url)[:16]}"

    # -- fields -------------------------------------------------------------

    def _extract_fields(
        self, text: str, detail_soup, cells: dict[str, str] | None = None
    ) -> dict[str, str | None]:
        fields: dict[str, str | None] = {}
        for spec in self.config.fields:
            value = value_from_cells(cells or {}, spec.labels)
            if value is None:
                value = labelled_value(text, spec.labels)
            if value is None and detail_soup is not None:
                value = cell_after_header(detail_soup, spec.labels)
            if value is None and detail_soup is not None:
                value = labelled_value(
                    normalise_text(detail_soup.get_text("\n")).replace("\n", " | "), spec.labels
                )
            if value is not None and spec.is_date:
                value = parse_stated_date(value) or value
            fields[spec.key] = value
        return fields

    def _published_at(self, row: str, detail_soup, cells: dict[str, str] | None = None) -> str | None:
        """The date the *source states* as publication. Never the fetch date."""
        labels = self.config.published_labels
        if not labels:
            return None
        for value in (
            value_from_cells(cells or {}, labels),
            labelled_value(row, labels),
            cell_after_header(detail_soup, labels) if detail_soup is not None else None,
        ):
            parsed = parse_stated_date(value) if value else None
            if parsed:
                return parsed
        return None

    # -- item building ------------------------------------------------------

    def _item_from_row(self, ctx: AdapterContext, row: dict[str, Any], *, detail_fetched: bool):
        notes = ["listing_only"] if not detail_fetched else []
        if row["published_at"] is None:
            notes.append(NOTE_PUBLISHED_AT_UNSTATED)
        body = "\n".join(part for part in (field_block(row["fields"]), row["row_text"]) if part)
        return self.make_item(
            item_id=row["id"],
            title=row["title"],
            url=row["url"],
            published_at=row["published_at"],
            body_text=body,
            fetched_at=ctx.now,
            http_status=200,
            archive_path=None,
            notes="; ".join(notes),
        )

    def _item_with_detail(self, ctx: AdapterContext, row: dict[str, Any], result: AdapterResult, previous):
        try:
            fetched, ref = self.fetch_and_archive(ctx, row["url"])
        except Exception as exc:
            result.warnings.append(f"{row['id']}: detail fetch failed: {exc}")
            item = self._item_from_row(ctx, row, detail_fetched=False)
            item.add_note(f"detail_fetch_failed: {type(exc).__name__}")
            return item

        if fetched.not_modified and previous is not None:
            return self.item_from_state(
                item_id=row["id"], previous=previous, fetched_at=ctx.now
            )

        result.page_bytes += len(fetched.body)
        soup = parse(fetched.text())
        fields = dict(row["fields"])
        detail_fields = self._extract_fields(row["row_text"], soup, row.get("cells"))
        for key, value in detail_fields.items():
            if fields.get(key) in (None, "") and value:
                fields[key] = value
        published_at = row["published_at"] or self._published_at(
            row["row_text"], soup, row.get("cells")
        )
        detail_text = normalise_text(soup.get_text("\n"))
        body = "\n".join(part for part in (field_block(fields), detail_text) if part)
        notes: list[str] = []
        if published_at is None:
            notes.append(NOTE_PUBLISHED_AT_UNSTATED)
        return self.make_item(
            item_id=row["id"],
            title=row["title"],
            url=row["url"],
            published_at=published_at,
            body_text=body,
            fetched_at=fetched.fetched_at,
            http_status=fetched.status,
            archive_path=ref.path if ref else None,
            notes="; ".join(notes),
        )
