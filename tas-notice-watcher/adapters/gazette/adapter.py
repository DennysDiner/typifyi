"""Tasmanian Government Gazette adapter.

See NOTES.md for what was verified about this source and what was not.

Shape of the source (as documented there): a per-year index page linking to one
PDF per issue, published weekly plus ad-hoc special gazettes. The adapter keys
on the *href shape* (a PDF under ``/editions/``) and on the issue number and
date carried in the link text or filename, which is far more durable than any
CSS selector.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from tnw.fetcher import FetchResult
from tnw.hashing import sha256_text
from tnw.models import NOTE_BODY_PENDING, NOTE_NO_TEXT_LAYER, NOTE_PUBLISHED_AT_UNSTATED
from tnw.normalise import canonical_url
from tnw.pdf import PdfExtractionError, extract_pdf_text
from tnw.timeutil import parse_iso, parse_stated_date

from ..base import Adapter, AdapterContext, AdapterParseError, AdapterResult, reraise_fetch_failure
from ..htmlutil import find_links, parse

BASE = "https://www.gazette.tas.gov.au"
PDF_LINK_RE = re.compile(r"(?i)/editions/[^?]*\.pdf$")
# "22542 - Gazette 14 January 2026", "22551_-_Special_Gazette_3_March_2026"
ISSUE_NUMBER_RE = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")
SPECIAL_RE = re.compile(r"(?i)special")
PERIODICAL_RE = re.compile(r"(?i)periodical")


class GazetteAdapter(Adapter):
    name = "gazette"
    label = "Tasmanian Government Gazette"
    # Published weekly (Wednesdays); a special gazette can appear any day.
    expected_interval_hours = 12.0  # we expect to *fetch* the index twice daily
    grace_hours = 24.0
    min_expected_items = 1
    supports_removals = False  # a year index only grows; withdrawal is not a thing here

    def candidate_urls(self, ctx: AdapterContext) -> list[str]:
        year = parse_iso(ctx.now).year
        urls = [f"{BASE}/editions/{year}"]
        # In early January the current-year index may hold only one or two
        # issues, so the previous year is still worth watching.
        if parse_iso(ctx.now).month == 1:
            urls.append(f"{BASE}/editions/{year - 1}")
        urls.append(f"{BASE}/")
        return urls

    def probe(self, result: FetchResult) -> dict[str, Any]:
        soup = parse(result.text())
        links = find_links(soup, result.final_url, PDF_LINK_RE)
        return {
            "pdf_links": len(links),
            "sample": [hit.url for hit in links[:3]],
            "has_feed": bool(soup.find("link", attrs={"type": re.compile("rss|atom")})),
        }

    # -- collection ---------------------------------------------------------

    def collect(self, ctx: AdapterContext) -> AdapterResult:
        result = AdapterResult()
        candidates = self.candidate_urls(ctx)
        index_urls = [url for url in candidates if "/editions/" in url]
        fallback_urls = [url for url in candidates if "/editions/" not in url]
        listings: list[tuple[str, str]] = []
        errors: list[str] = []
        fetch_failures: list[tuple[str, Exception]] = []
        unchanged = 0

        def fetch_listing(url: str) -> None:
            nonlocal unchanged
            try:
                fetched, _ref = self.fetch_and_archive(ctx, url)
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
                fetch_failures.append((url, exc))
                return
            if fetched.not_modified:
                unchanged += 1
                result.notes.append(f"{url}: 304 not modified")
                return
            result.page_bytes += len(fetched.body)
            listings.append((fetched.final_url, fetched.text()))
            if result.endpoint is None:
                result.endpoint = url

        for url in index_urls:
            fetch_listing(url)

        if not listings and unchanged:
            # The index returned 304: nothing has changed since the last run, so
            # there is nothing to re-parse and no reason to try the fallback.
            result.listing_unchanged = True
            result.endpoint = ctx.state.endpoint
            return result

        entries: dict[str, dict[str, Any]] = {}
        for base_url, html in listings:
            for entry in self._extract_entries(base_url, html):
                entries.setdefault(entry["id"], entry)

        # The site root is only consulted when the year index gave us nothing,
        # so a working index never costs an extra request.
        if not entries and not unchanged:
            for url in fallback_urls:
                fetch_listing(url)
            for base_url, html in listings:
                for entry in self._extract_entries(base_url, html):
                    entries.setdefault(entry["id"], entry)

        if not listings:
            reraise_fetch_failure(self.name, fetch_failures)
            raise AdapterParseError(
                "no gazette index page could be fetched: "
                + ("; ".join(errors) or "no candidate URLs produced a response")
            )

        if not entries:
            raise AdapterParseError(
                "gazette index fetched but no issue PDFs were found: the page "
                f"structure has changed (checked {len(listings)} page(s), "
                f"{result.page_bytes} bytes)"
            )

        ordered = sorted(
            entries.values(),
            key=lambda e: (e["published_at"] or "", e["number"] or ""),
            reverse=True,
        )
        budget = ctx.limits.max_documents
        for entry in ordered:
            previous = ctx.state.items.get(entry["id"])
            listing_unchanged = (
                previous is not None
                and not previous.body_pending
                and previous.title == entry["title"]
                and previous.url == entry["url"]
                and previous.published_at == entry["published_at"]
            )
            if listing_unchanged:
                # Gazette issues are immutable once published: an unchanged
                # listing entry means there is nothing to re-download.
                item = self.item_from_state(
                    item_id=entry["id"],
                    previous=previous,
                    fetched_at=ctx.now,
                    note="unchanged_listing_entry",
                )
                item.http_status = 200
                result.items.append(item)
                continue

            if budget <= 0:
                item = self._item_without_body(entry, ctx)
                result.items.append(item)
                result.warnings.append(
                    f"{entry['id']}: document not downloaded this run (budget "
                    f"{ctx.limits.max_documents}); text will be collected next run"
                )
                continue

            budget -= 1
            result.items.append(self._item_with_body(entry, ctx, result))

        return result

    # -- extraction ---------------------------------------------------------

    def _extract_entries(self, base_url: str, html: str) -> list[dict[str, Any]]:
        soup = parse(html)
        entries: list[dict[str, Any]] = []
        for hit in find_links(soup, base_url, PDF_LINK_RE):
            url = canonical_url(urljoin(base_url, hit.url))
            filename = url.rsplit("/", 1)[-1]
            readable = filename.replace("_", " ").replace("%20", " ")
            label = hit.text.strip() or readable.rsplit(".", 1)[0]
            number_match = ISSUE_NUMBER_RE.search(label) or ISSUE_NUMBER_RE.search(readable)
            number = number_match.group(1) if number_match else None
            published_at = parse_stated_date(label) or parse_stated_date(readable)
            kind = (
                "special"
                if SPECIAL_RE.search(label) or SPECIAL_RE.search(readable)
                else "periodical"
                if PERIODICAL_RE.search(label) or PERIODICAL_RE.search(readable)
                else "regular"
            )
            item_id = f"gazette:{number}" if number else f"gazette:url:{sha256_text(url)[:16]}"
            title = label if label else f"Gazette {number or item_id}"
            entries.append(
                {
                    "id": item_id,
                    "number": number,
                    "title": " ".join(title.split()),
                    "url": url,
                    "published_at": published_at,
                    "kind": kind,
                }
            )
        return entries

    def _notes_for(self, entry: dict[str, Any]) -> str:
        notes = [f"kind: {entry['kind']}"]
        if entry["published_at"] is None:
            notes.append(NOTE_PUBLISHED_AT_UNSTATED)
        if entry["number"] is None:
            notes.append("issue_number_not_found_in_link")
        return "; ".join(notes)

    def _item_without_body(self, entry: dict[str, Any], ctx: AdapterContext):
        notes = self._notes_for(entry)
        item = self.make_item(
            item_id=entry["id"],
            title=entry["title"],
            url=entry["url"],
            published_at=entry["published_at"],
            body_text="",
            fetched_at=ctx.now,
            http_status=None,
            archive_path=None,
            notes=f"{notes}; {NOTE_BODY_PENDING}",
        )
        return item

    def _item_with_body(self, entry: dict[str, Any], ctx: AdapterContext, result: AdapterResult):
        notes = self._notes_for(entry)
        try:
            fetched, ref = self.fetch_and_archive(ctx, entry["url"], accept="application/pdf")
        except Exception as exc:
            result.warnings.append(f"{entry['id']}: PDF fetch failed: {exc}")
            item = self._item_without_body(entry, ctx)
            item.add_note(f"pdf_fetch_failed: {type(exc).__name__}")
            return item

        if fetched.not_modified:
            previous = ctx.state.items.get(entry["id"])
            if previous is not None:
                return self.item_from_state(
                    item_id=entry["id"], previous=previous, fetched_at=ctx.now
                )

        result.page_bytes += len(fetched.body)
        body = ""
        try:
            extracted = extract_pdf_text(fetched.body, max_pages=ctx.limits.max_pdf_pages)
        except PdfExtractionError as exc:
            result.warnings.append(f"{entry['id']}: {exc}")
            notes = f"{notes}; pdf_unreadable: {exc}"
        else:
            body = extracted.text
            notes = f"{notes}; pages: {extracted.page_count}"
            if extracted.truncated:
                notes += f"; pages_read: {extracted.pages_read}"
                result.warnings.append(
                    f"{entry['id']}: only the first {extracted.pages_read} of "
                    f"{extracted.page_count} pages were read"
                )
            if not extracted.has_text_layer:
                notes += f"; {NOTE_NO_TEXT_LAYER}"
                result.warnings.append(
                    f"{entry['id']}: no usable text layer ({len(body)} chars from "
                    f"{extracted.page_count} pages) — OCR would be required to read this issue"
                )

        return self.make_item(
            item_id=entry["id"],
            title=entry["title"],
            url=entry["url"],
            published_at=entry["published_at"],
            body_text=body,
            fetched_at=fetched.fetched_at,
            http_status=fetched.status,
            archive_path=ref.path if ref else None,
            notes=notes,
        )
