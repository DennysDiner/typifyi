"""Tenders, contracts and lobbyist adapters, against saved fixtures only (§7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeFetcher, Route

from adapters.base import AdapterContext, AdapterParseError, Limits
from adapters.contracts import ContractsAdapter
from adapters.lobbyists import LobbyistsAdapter
from adapters.tenders import TendersAdapter
from tnw.archive import LocalGzipArchiveWriter
from tnw.state import ItemState, SourceState

NOW = "2026-08-31T21:05:00Z"
TENDER_LIST = "https://www.tenders.tas.gov.au/tender/list"
TENDER_PAGE2 = "https://www.tenders.tas.gov.au/Tender/List?page=2"
TENDER_DETAIL = "https://www.tenders.tas.gov.au/Tender/View/48211"
CONTRACT_LIST = "https://www.tenders.tas.gov.au/ContractAwarded/List/DateAwarded"
CONTRACT_DETAIL = "https://www.tenders.tas.gov.au/ContractAwarded/View/90212"
REGISTER = "https://lobbyists.integrity.tas.gov.au/register"
FONT = "https://lobbyists.integrity.tas.gov.au/lobbyists/font_public_relations"


def context(tmp_path: Path, routes, *, source: str, state=None, limits=None):
    fetcher = FakeFetcher(routes, now=NOW)
    return AdapterContext(
        fetcher=fetcher,
        archive=LocalGzipArchiveWriter(tmp_path / "archive"),
        state=state or SourceState(source=source),
        now=NOW,
        limits=limits or Limits(),
    ), fetcher


def tender_routes(**overrides):
    routes = {
        TENDER_LIST: Route.html("tenders", "tender-list.html"),
        TENDER_PAGE2: Route.html("tenders", "tender-list-page2.html"),
        TENDER_DETAIL: Route.html("tenders", "tender-detail-48211.html"),
        "https://www.tenders.tas.gov.au/Tender/View/48212": Route.html("tenders", "tender-detail-48211.html"),
        "https://www.tenders.tas.gov.au/Tender/View/48213": Route.html("tenders", "tender-detail-48211.html"),
        "https://www.tenders.tas.gov.au/Tender/View/48200": Route.html("tenders", "tender-detail-48211.html"),
    }
    routes.update(overrides)
    return routes


# -- tenders -----------------------------------------------------------------


def test_tenders_are_extracted_with_their_stated_fields(tmp_path):
    ctx, _ = context(tmp_path, tender_routes(), source="tenders")
    result = TendersAdapter().collect(ctx)
    by_id = {item.id: item for item in result.items}

    assert result.endpoint == TENDER_LIST
    assert "tenders:48211" in by_id
    item = by_id["tenders:48211"]
    assert item.title.startswith("Road maintenance services")
    assert item.published_at == "2026-08-26"  # stated "Published" column
    assert "agency: Department of State Growth" in item.body_text
    assert "closing_date: 2026-09-17" in item.body_text
    assert "tender_id: DSG-2026-114" in item.body_text
    assert item.archive_path and Path(item.archive_path).exists()


def test_tenders_follow_pagination(tmp_path):
    ctx, _ = context(tmp_path, tender_routes(), source="tenders")
    result = TendersAdapter().collect(ctx)
    assert "tenders:48200" in {item.id for item in result.items}


def test_a_listing_with_no_matching_rows_raises(tmp_path):
    routes = {
        TENDER_LIST: Route(body=b"<html><body><p>No tenders</p></body></html>"),
        "https://www.tenders.tas.gov.au/Tender/List": Route(body=b"<html><body></body></html>"),
        "https://www.tenders.tas.gov.au/tender/search": Route(body=b"<html><body></body></html>"),
        "https://www.tenders.tas.gov.au/": Route(body=b"<html><body></body></html>"),
    }
    ctx, _ = context(tmp_path, routes, source="tenders")
    with pytest.raises(AdapterParseError) as excinfo:
        TendersAdapter().collect(ctx)
    assert "no rows extracted" in str(excinfo.value)


def test_the_first_working_candidate_is_used_and_recorded(tmp_path):
    """The primary candidate 404s; the adapter falls through and says which worked."""
    routes = tender_routes()
    routes.pop(TENDER_LIST)
    routes["https://www.tenders.tas.gov.au/Tender/List"] = Route.html("tenders", "tender-list.html")
    ctx, _ = context(tmp_path, routes, source="tenders")
    result = TendersAdapter().collect(ctx)
    assert result.endpoint == "https://www.tenders.tas.gov.au/Tender/List"
    assert result.items


def test_an_unchanged_row_is_not_re_fetched(tmp_path):
    ctx, fetcher = context(tmp_path, tender_routes(), source="tenders")
    adapter = TendersAdapter()
    first = adapter.collect(ctx)
    for item in first.items:
        ctx.state.items[item.id] = ItemState(
            content_hash=item.content_hash, title=item.title, url=item.url,
            published_at=item.published_at, archive_path=item.archive_path,
            first_seen_at=NOW, last_seen_at=NOW,
            listing_hash=first.listing_hashes.get(item.id, ""),
        )
    before = sum(1 for url, _ in fetcher.calls if "/View/" in url)
    second = adapter.collect(ctx)
    after = sum(1 for url, _ in fetcher.calls if "/View/" in url)

    assert after == before, "an unchanged listing row must not cost a detail fetch"
    assert {i.content_hash for i in second.items} == {i.content_hash for i in first.items}


def test_detail_budget_is_respected_and_reported(tmp_path):
    ctx, fetcher = context(tmp_path, tender_routes(), source="tenders", limits=Limits(max_detail_pages=1))
    result = TendersAdapter().collect(ctx)
    assert sum(1 for url, _ in fetcher.calls if "/View/" in url) == 1
    assert any("detail page not fetched" in warning for warning in result.warnings)
    listing_only = [item for item in result.items if item.has_note("listing_only")]
    assert listing_only and all(item.body_text for item in listing_only)


# -- contracts ---------------------------------------------------------------


def contract_routes():
    return {
        CONTRACT_LIST: Route.html("contracts", "contract-list.html"),
        "https://www.tenders.tas.gov.au/ContractAwarded/View/90211": Route.html(
            "contracts", "contract-detail-90212.html"
        ),
        CONTRACT_DETAIL: Route.html("contracts", "contract-detail-90212.html"),
    }


def test_award_date_is_never_promoted_into_the_publication_date(tmp_path):
    """§9.4: the gap between award and disclosure is the finding; do not erase it."""
    ctx, _ = context(tmp_path, contract_routes(), source="contracts")
    result = ContractsAdapter().collect(ctx)
    item = next(i for i in result.items if i.id == "contracts:90212")

    assert item.published_at is None
    assert item.has_note("published_at_not_stated_by_source")
    assert "date_awarded: 2026-07-21" in item.body_text
    assert "supplier: Ta Ann Tasmania Pty Ltd" in item.body_text
    assert "value: $3,980,500" in item.body_text


def test_contract_removals_are_not_emitted(tmp_path):
    assert ContractsAdapter().supports_removals is False
    assert TendersAdapter().supports_removals is True
    assert LobbyistsAdapter().supports_removals is True


# -- lobbyists ---------------------------------------------------------------


def lobbyist_routes(font="detail-font.html"):
    routes = {
        REGISTER: Route.html("lobbyists", "register.html"),
        FONT: Route.html("lobbyists", font, etag='"font-v1"'),
    }
    for slug in (
        "tg_public_affairs_pty_ltd",
        "regs_and_corporate_advisory_pty_ltd",
        "premiernational_pty_ltd",
    ):
        routes[f"https://lobbyists.integrity.tas.gov.au/lobbyists/{slug}"] = Route.html(
            "lobbyists", f"detail-{slug}.html"
        )
    return routes


def test_the_register_yields_one_item_per_lobbyist_with_clients(tmp_path):
    ctx, _ = context(tmp_path, lobbyist_routes(), source="lobbyists")
    result = LobbyistsAdapter().collect(ctx)
    by_id = {item.id: item for item in result.items}

    assert len(by_id) == 4
    font = by_id["lobbyists:font_public_relations"]
    assert font.title == "Font Public Relations"
    assert "Federal Group" in font.body_text and "Hydro Tasmania" in font.body_text
    assert font.published_at == "2023-03-03"  # stated "Date registered"


def test_a_new_client_changes_the_hash_even_though_the_index_did_not_change(tmp_path):
    adapter = LobbyistsAdapter()
    ctx, _ = context(tmp_path, lobbyist_routes(), source="lobbyists")
    first = {i.id: i for i in adapter.collect(ctx).items}

    ctx2, _ = context(tmp_path, lobbyist_routes("detail-font-changed.html"), source="lobbyists")
    second = {i.id: i for i in adapter.collect(ctx2).items}

    assert first["lobbyists:font_public_relations"].content_hash != (
        second["lobbyists:font_public_relations"].content_hash
    )
    assert "Nyrstar Hobart Pty Ltd" in second["lobbyists:font_public_relations"].body_text
    # The other three pages are unchanged and must hash identically.
    for item_id in set(first) - {"lobbyists:font_public_relations"}:
        assert first[item_id].content_hash == second[item_id].content_hash


def test_a_304_on_a_detail_page_reuses_the_stored_hash(tmp_path):
    """A conditional GET saying "not modified" is evidence of no change."""
    adapter = LobbyistsAdapter()
    state = SourceState(source="lobbyists")
    state.record_validator(FONT, {"ETag": '"font-v1"'})
    state.items["lobbyists:font_public_relations"] = ItemState(
        content_hash="c" * 64,
        title="Font Public Relations",
        url=FONT,
        published_at="2023-03-03",
        archive_path="archive/2026/08/lobbyists/old.html.gz",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    ctx, _ = context(tmp_path, lobbyist_routes(), source="lobbyists", state=state)
    result = adapter.collect(ctx)
    font = next(i for i in result.items if i.id == "lobbyists:font_public_relations")
    assert font.content_hash == "c" * 64
    assert font.http_status == 304
    assert font.archive_path == "archive/2026/08/lobbyists/old.html.gz"
