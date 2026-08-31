"""M4 outputs: Atom feed, weekly digest, NDJSON export."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from tnw.models import Item
from tnw.outputs import export_ndjson, latest_by_id, recent_records, render_atom, render_digest, write_feed
from tnw.records import append_items

ATOM = "{http://www.w3.org/2005/Atom}"
NOW = "2026-08-31T21:05:00Z"


def seed(records_dir: Path) -> None:
    append_items(
        records_dir,
        "gazette",
        [
            Item(id="gazette:22599", source="gazette", title="22599 - Gazette 12 August 2026",
                 url="https://www.gazette.tas.gov.au/a.pdf", published_at="2026-08-12",
                 body_text="Nyrstar", entities=["Nyrstar"], content_hash="a" * 64,
                 fetched_at="2026-08-30T21:05:00Z", http_status=200,
                 archive_path="archive/2026/08/gazette/a.pdf.gz"),
            Item(id="gazette:supp", source="gazette", title="Supplement",
                 url="https://www.gazette.tas.gov.au/s.pdf", published_at=None,
                 content_hash="b" * 64, fetched_at=NOW, http_status=200,
                 archive_path="archive/2026/08/gazette/b.pdf.gz",
                 source_notes="published_at_not_stated_by_source"),
        ],
    )
    append_items(
        records_dir,
        "tenders",
        [
            Item(id="tenders:48211", source="tenders", title="Road maintenance services",
                 url="https://www.tenders.tas.gov.au/Tender/View/48211",
                 published_at="2026-08-26", content_hash="c" * 64, fetched_at=NOW,
                 http_status=200, archive_path="archive/2026/08/tenders/c.html.gz"),
        ],
    )


def test_the_feed_is_valid_atom_and_carries_provenance(tmp_path: Path):
    seed(tmp_path)
    out = write_feed(tmp_path, tmp_path / "outputs" / "feed.xml", self_url="https://example/feed.xml")
    tree = ET.parse(out)
    root = tree.getroot()

    assert root.tag == f"{ATOM}feed"
    assert root.find(f"{ATOM}title") is not None
    assert root.find(f"{ATOM}id") is not None
    assert root.find(f"{ATOM}updated") is not None
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 3
    for entry in entries:
        assert entry.find(f"{ATOM}id") is not None
        assert entry.find(f"{ATOM}title") is not None
        assert entry.find(f"{ATOM}updated") is not None
        summary = entry.find(f"{ATOM}summary").text
        assert "archive:" in summary and "content hash:" in summary


def test_the_feed_states_when_a_date_was_not_stated(tmp_path: Path):
    seed(tmp_path)
    xml = render_atom(recent_records(tmp_path))
    assert "stated publication date: not stated by source" in xml
    assert "stated publication date: 2026-08-12" in xml


def test_the_feed_escapes_hostile_content(tmp_path: Path):
    append_items(
        tmp_path,
        "tenders",
        [
            Item(id="tenders:1", source="tenders", title="Tender <script>alert(1)</script> & co",
                 url="https://www.tenders.tas.gov.au/Tender/View/1?a=1&b=2",
                 published_at=None, content_hash="d" * 64, fetched_at=NOW, http_status=200),
        ],
    )
    xml = render_atom(recent_records(tmp_path))
    ET.fromstring(xml)
    assert "<script>" not in xml


def test_only_the_newest_record_for_an_item_is_published(tmp_path: Path):
    seed(tmp_path)
    append_items(
        tmp_path,
        "tenders",
        [Item(id="tenders:48211", source="tenders", title="Road maintenance services (amended)",
              url="https://www.tenders.tas.gov.au/Tender/View/48211", published_at="2026-08-26",
              content_hash="e" * 64, fetched_at="2026-09-01T07:05:00Z", http_status=200)],
    )
    rows = latest_by_id(recent_records(tmp_path))
    titles = {row["id"]: row["title"] for row in rows}
    assert titles["tenders:48211"].endswith("(amended)")
    assert len(rows) == 3


def test_the_digest_counts_entities_and_undated_records(tmp_path: Path):
    seed(tmp_path)
    digest = render_digest(recent_records(tmp_path), days=7, generated_at=NOW)
    assert "items recorded: **3**" in digest.body
    assert "stated no publication date: **1**" in digest.body
    assert "**Nyrstar**: 1" in digest.body
    assert "## gazette (2)" in digest.body
    assert "machine-summarised" in digest.body


def test_export_writes_oldest_first_and_honours_since(tmp_path: Path):
    seed(tmp_path)
    out, count = export_ndjson(tmp_path, tmp_path / "outputs" / "export.ndjson")
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert count == 3
    assert [row["fetched_at"] for row in rows] == sorted(row["fetched_at"] for row in rows)

    _, recent = export_ndjson(tmp_path, tmp_path / "outputs" / "recent.ndjson", since=NOW)
    assert recent == 2


def test_export_can_be_filtered_by_source(tmp_path: Path):
    seed(tmp_path)
    _, count = export_ndjson(tmp_path, tmp_path / "out.ndjson", sources=["tenders"])
    assert count == 1
