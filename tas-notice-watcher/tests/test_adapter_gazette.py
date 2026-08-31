"""Gazette adapter, against saved fixtures only (§7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeFetcher, Route

from adapters.base import AdapterContext, AdapterParseError, Limits
from tnw.fetcher import StructuralFetchError
from adapters.gazette import GazetteAdapter
from tnw.archive import LocalGzipArchiveWriter
from tnw.models import NOTE_BODY_PENDING, NOTE_NO_TEXT_LAYER
from tnw.state import ItemState, SourceState

NOW = "2026-08-31T21:05:00Z"
INDEX = "https://www.gazette.tas.gov.au/editions/2026"
HOME = "https://www.gazette.tas.gov.au/"
PDF_22599 = "https://www.gazette.tas.gov.au/editions/2026/august-2026/22599_-_Gazette_12_August_2026.pdf"
PDF_22598 = "https://www.gazette.tas.gov.au/editions/2026/august-2026/22598_-_Special_Gazette_5_August_2026.pdf"
PDF_22590 = "https://www.gazette.tas.gov.au/editions/2026/july-2026/22590_-_Gazette_1_July_2026.pdf"
PDF_SUPPLEMENT = "https://www.gazette.tas.gov.au/editions/2026/supplements/notice_supplement.pdf"


def build(tmp_path: Path, *, index_fixture="editions-2026.html", state=None, limits=None,
          pdf_fixture="sample-gazette.pdf", routes=None):
    table = {
        INDEX: Route.html("gazette", index_fixture, etag='"index-v1"'),
        HOME: Route.html("gazette", index_fixture),
        PDF_22599: Route.pdf("gazette", pdf_fixture),
        PDF_22598: Route.pdf("gazette", pdf_fixture),
        PDF_22590: Route.pdf("gazette", pdf_fixture),
        PDF_SUPPLEMENT: Route.pdf("gazette", pdf_fixture),
    }
    table.update(routes or {})
    fetcher = FakeFetcher(table, now=NOW)
    ctx = AdapterContext(
        fetcher=fetcher,
        archive=LocalGzipArchiveWriter(tmp_path / "archive"),
        state=state or SourceState(source="gazette"),
        now=NOW,
        limits=limits or Limits(),
    )
    return GazetteAdapter(), ctx, fetcher


def test_issues_are_extracted_with_stated_numbers_and_dates(tmp_path):
    adapter, ctx, _ = build(tmp_path)
    result = adapter.collect(ctx)
    by_id = {item.id: item for item in result.items}

    assert set(by_id) >= {"gazette:22599", "gazette:22598", "gazette:22590"}
    issue = by_id["gazette:22599"]
    assert issue.published_at == "2026-08-12"
    assert issue.url == PDF_22599
    assert issue.http_status == 200
    assert issue.archive_path and Path(issue.archive_path).exists()
    assert "Nyrstar Hobart smelter" in issue.body_text
    assert by_id["gazette:22598"].has_note("kind")
    assert "special" in by_id["gazette:22598"].source_notes


def test_an_issue_without_a_stated_date_is_flagged_not_backfilled(tmp_path):
    """§2.4: published_at must never be back-filled with the fetch date."""
    adapter, ctx, _ = build(tmp_path)
    supplement = [i for i in adapter.collect(ctx).items if "supplement" in i.url]
    assert supplement, "the supplement link should still be extracted"
    assert supplement[0].published_at is None
    assert supplement[0].has_note("published_at_not_stated_by_source")
    assert NOW not in (supplement[0].published_at or "")


def test_a_broken_page_raises_instead_of_returning_nothing(tmp_path):
    """§5/M2: a selector that stops matching must fail loudly."""
    adapter, ctx, _ = build(tmp_path, index_fixture="editions-2026-broken.html")
    with pytest.raises(AdapterParseError) as excinfo:
        adapter.collect(ctx)
    assert "no issue PDFs were found" in str(excinfo.value)


def test_an_image_only_pdf_is_reported_not_silently_empty(tmp_path):
    adapter, ctx, _ = build(tmp_path, pdf_fixture="scanned-gazette.pdf")
    result = adapter.collect(ctx)
    issue = next(i for i in result.items if i.id == "gazette:22599")
    assert NOTE_NO_TEXT_LAYER in issue.source_notes
    assert any("no usable text layer" in warning for warning in result.warnings)


def test_document_budget_defers_downloads_and_says_so(tmp_path):
    adapter, ctx, fetcher = build(tmp_path, limits=Limits(max_documents=1))
    result = adapter.collect(ctx)
    fetched = [item for item in result.items if not item.has_note(NOTE_BODY_PENDING)]
    pending = [item for item in result.items if item.has_note(NOTE_BODY_PENDING)]
    assert len(fetched) == 1
    assert pending and all(item.body_text == "" for item in pending)
    assert any("not downloaded this run" in warning for warning in result.warnings)
    # Newest first: the most recent issue is the one that gets downloaded.
    assert fetched[0].id == "gazette:22599"


def test_a_known_unchanged_issue_is_not_downloaded_again(tmp_path):
    # No ETag on the index here: this test is about the *listing entry* being
    # unchanged, not about conditional GET short-circuiting the whole run.
    adapter, ctx, fetcher = build(
        tmp_path, routes={INDEX: Route.html("gazette", "editions-2026.html")}
    )
    first = adapter.collect(ctx)
    for item in first.items:
        ctx.state.items[item.id] = ItemState(
            content_hash=item.content_hash,
            title=item.title,
            url=item.url,
            published_at=item.published_at,
            archive_path=item.archive_path,
            first_seen_at=NOW,
            last_seen_at=NOW,
            body_pending=item.has_note(NOTE_BODY_PENDING),
        )
    pdf_requests_before = sum(1 for url, _ in fetcher.calls if url.endswith(".pdf"))
    second = adapter.collect(ctx)
    pdf_requests_after = sum(1 for url, _ in fetcher.calls if url.endswith(".pdf"))

    assert pdf_requests_after == pdf_requests_before, "immutable issues must not be re-downloaded"
    assert {i.content_hash for i in second.items} == {i.content_hash for i in first.items}


def test_a_304_on_the_index_means_nothing_to_do(tmp_path):
    state = SourceState(source="gazette")
    state.record_validator(INDEX, {"ETag": '"index-v1"'})
    state.endpoint = INDEX
    adapter, ctx, _ = build(
        tmp_path,
        state=state,
        routes={HOME: Route.html("gazette", "editions-2026-broken.html", etag='"home-v1"')},
    )
    # The home fallback is only consulted when the index yields nothing, and a
    # 304 index is not "nothing" — it is "unchanged".
    result = adapter.collect(ctx)
    assert result.listing_unchanged is True
    assert result.items == []


def test_a_missing_index_is_a_fetch_failure_not_an_empty_result(tmp_path):
    """A 404 on every candidate keeps its own failure kind, for triage."""
    adapter, ctx, _ = build(tmp_path)
    ctx.fetcher.routes.pop(INDEX)
    ctx.fetcher.routes.pop(HOME)
    with pytest.raises(StructuralFetchError) as excinfo:
        adapter.collect(ctx)
    assert "no candidate endpoint could be fetched for gazette" in str(excinfo.value)


def test_listing_html_is_archived_for_provenance(tmp_path):
    adapter, ctx, _ = build(tmp_path)
    adapter.collect(ctx)
    archived = list((tmp_path / "archive").rglob("*.gz"))
    assert any(path.name.endswith(".html.gz") for path in archived)
    assert any(path.name.endswith(".pdf.gz") for path in archived)
