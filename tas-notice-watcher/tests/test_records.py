"""The append-only record store (§2.2, §5)."""

from __future__ import annotations

import json
from pathlib import Path

from tnw.models import NOTE_BODY_TRUNCATED, Item, validate_record
from tnw.records import append_items, month_path, read_records

NOW = "2026-08-31T21:05:00Z"


def make_item(item_id="tenders:1", **overrides) -> Item:
    base = dict(
        id=item_id, source="tenders", title="A tender", url="https://x.tas.gov.au/a",
        published_at="2026-08-26", body_text="body", content_hash="a" * 64,
        fetched_at=NOW, http_status=200, archive_path="archive/x.gz",
    )
    base.update(overrides)
    return Item(**base)


def test_records_are_appended_one_file_per_source_per_month(tmp_path: Path):
    written, errors = append_items(tmp_path, "tenders", [make_item(), make_item("tenders:2")])
    assert (written, errors) == (2, [])
    target = month_path(tmp_path, "tenders", NOW)
    assert target.name == "tenders-2026-08.ndjson"

    append_items(tmp_path, "tenders", [make_item("tenders:3")])
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert [row["id"] for row in rows] == ["tenders:1", "tenders:2", "tenders:3"]
    assert all(validate_record(row) == [] for row in rows)


def test_records_split_by_month(tmp_path: Path):
    append_items(tmp_path, "tenders", [make_item()])
    append_items(tmp_path, "tenders", [make_item("tenders:9", fetched_at="2026-09-01T00:00:00Z")])
    names = sorted(path.name for path in tmp_path.glob("*.ndjson"))
    assert names == ["tenders-2026-08.ndjson", "tenders-2026-09.ndjson"]


def test_an_invalid_record_is_rejected_and_reported_not_half_written(tmp_path: Path):
    good = make_item("tenders:good")
    bad = make_item("tenders:bad", content_hash="short")
    written, errors = append_items(tmp_path, "tenders", [good, bad])

    assert written == 1
    assert [error.item_id for error in errors] == ["tenders:bad"]
    rows = list(read_records(tmp_path))
    assert [row["id"] for row in rows] == ["tenders:good"]


def test_long_bodies_are_truncated_in_the_record_and_say_so(tmp_path: Path):
    item = make_item(body_text="x" * 5000)
    append_items(tmp_path, "tenders", [item], max_body_chars=100)
    [row] = list(read_records(tmp_path))
    assert len(row["body_text"]) == 100
    assert NOTE_BODY_TRUNCATED in row["source_notes"]
    assert "full text in archive" in row["source_notes"]


def test_reading_filters_by_source(tmp_path: Path):
    append_items(tmp_path, "tenders", [make_item()])
    append_items(tmp_path, "gazette", [make_item("gazette:1", source="gazette")])
    assert {row["source"] for row in read_records(tmp_path, sources=["gazette"])} == {"gazette"}
    assert len(list(read_records(tmp_path))) == 2


def test_empty_input_writes_nothing(tmp_path: Path):
    assert append_items(tmp_path, "tenders", []) == (0, [])
    assert list(tmp_path.glob("*.ndjson")) == []
