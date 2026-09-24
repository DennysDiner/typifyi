from make_pdf import simple_pdf

from rti_tracker.adapters.base import get_adapter
from tests.conftest import fixture_bytes

BASE = "https://example.tas.gov.au/rti/log"


def test_html_table():
    items = get_adapter("html_table").parse(fixture_bytes("table_log.html"), BASE, {})
    assert len(items) == 3
    by_ref = {i.reference: i for i in items}
    a = by_ref["RTI 2026-27/012"]
    assert a.published_date == "2026-08-14"
    assert "Nyrstar" in a.title
    assert a.document_urls == ["https://example.tas.gov.au/__data/assets/pdf_file/0011/1234/rti-2026-27-012.pdf"]
    assert a.fields["decision"].startswith("Released in part")
    assert by_ref["RTI 2026-27/011"].published_date == "2026-08-07"
    c = by_ref["RTI 2026-27/010"]
    assert c.published_date == "2026-07-30" and not c.document_urls and c.page_url and c.page_url.endswith("/rti/releases/2026-27-010")
    # keys are stable across re-parses
    again = get_adapter("html_table").parse(fixture_bytes("table_log.html"), BASE, {})
    assert {i.external_key for i in again} == {i.external_key for i in items}


def test_html_list_and_pagination():
    ad = get_adapter("html_list")
    items = ad.parse(fixture_bytes("list_log.html"), BASE, {"item_selector": "ul.disclosures > li", "next_selector": "a.next"})
    assert len(items) == 3
    assert items[0].reference == "RTI-045"
    assert items[0].published_date == "2026-08-12" and len(items[0].document_urls) == 2
    assert items[2].document_urls[0].endswith(".docx") and items[2].published_date == "2026-07-29"
    assert ad.next_page(fixture_bytes("list_log.html"), BASE, {"next_selector": "a.next"}) == "https://example.tas.gov.au/rti/disclosures?page=2"
    # heuristic mode (no selector) also finds the three entries
    assert len(get_adapter("html_list").parse(fixture_bytes("list_log.html"), BASE, {})) == 3


def test_per_release_pages_expand():
    ad = get_adapter("per_release_pages")
    items = ad.parse(fixture_bytes("index_pages.html"), BASE, {"item_selector": "article"})
    assert len(items) == 2 and all(it.page_url for it in items) and not any(it.document_urls for it in items)
    pages = {"https://example.tas.gov.au/about/routine-disclosures/right-information/rti-2026-27-021": fixture_bytes("release_page_021.html")}
    it = ad.expand(items[0], lambda u: pages[u], {})
    assert len(it.document_urls) == 2 and it.document_urls[0].endswith("_decision.pdf")
    assert "s 36" in it.fields["page_text"]


def test_auto_picks_table():
    ad = get_adapter("auto")
    cfg = {}
    items = ad.parse(fixture_bytes("table_log.html"), BASE, cfg)
    assert len(items) == 3 and cfg["detected_format"] == "html_table"


def test_pdf_index():
    pdf = simple_pdf([
        "Right to Information disclosure log 2026",
        "RTI-2026-01 Forestry coupe harvest plans 12/02/2026",
        "RTI-2026-02 Correspondence with Trafigura re grant deed 3 March 2026",
        "Page 1 of 1",
    ])
    items = get_adapter("pdf_index").parse(pdf, "https://example.tas.gov.au/rti/log.pdf", {})
    assert len(items) == 2
    assert items[0].reference == "RTI-2026-01" and items[0].published_date == "2026-02-12"
    assert "Trafigura" in items[1].title and items[1].published_date == "2026-03-03"


def test_ombudsman_decisions_reference_and_authority():
    html = b"""<html><body><ul><li><a href="/decisions/R2601-004.pdf">R2601-004 Smith and Department of Health (2026)</a> 3 February 2026</li></ul></body></html>"""
    items = get_adapter("ombudsman_decisions").parse(html, "https://www.ombudsman.tas.gov.au/rti/decisions", {})
    assert items[0].reference == "R2601-004" and items[0].fields["authority_raw"].startswith("Department of Health")


def test_annual_report_listing_years():
    html = b"""<html><body><ul><li><a href="/__data/assets/pdf_file/0011/1/RTI_Annual_Report_2024-25.pdf">Right to Information Annual Report 2024-25 (PDF)</a></li>
    <li><a href="/__data/assets/pdf_file/0011/2/RTI_Annual_Report_2023-24.pdf">Right to Information Annual Report 2023-24 (PDF)</a></li></ul></body></html>"""
    items = get_adapter("annual_report").parse(html, "https://www.justice.tas.gov.au/x", {})
    assert {i.fields["report_year"] for i in items} == {"2024-25", "2023-24"}
