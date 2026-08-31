"""Item schema validation (§2.4, §5)."""

from __future__ import annotations

import pytest

from tnw.models import (
    FIELD_ORDER,
    FLAG_PUBLISHED_AT_MISSING,
    Item,
    SchemaError,
    validate_record,
)


def make_item(**overrides) -> Item:
    base = dict(
        id="gazette:22599",
        source="gazette",
        title="22599 - Gazette 12 August 2026",
        url="https://www.gazette.tas.gov.au/editions/2026/x.pdf",
        published_at="2026-08-12",
        body_text="text",
        content_hash="a" * 64,
        fetched_at="2026-08-31T21:05:00Z",
        http_status=200,
        archive_path="archive/2026/08/gazette/abc.pdf.gz",
    )
    base.update(overrides)
    return Item(**base)


def test_record_is_written_in_schema_order():
    assert list(make_item().to_record()) == list(FIELD_ORDER)


def test_a_well_formed_record_validates():
    assert validate_record(make_item().to_record()) == []


def test_missing_publication_date_is_allowed_but_flagged():
    item = make_item(published_at=None)
    assert validate_record(item.to_record()) == []
    assert FLAG_PUBLISHED_AT_MISSING in item.flags


@pytest.mark.parametrize(
    "overrides, expected_fragment",
    [
        ({"source": "weather"}, "source"),
        ({"url": "/relative/path"}, "url"),
        ({"published_at": "12 August 2026"}, "published_at"),
        ({"content_hash": "not-a-hash"}, "content_hash"),
        ({"fetched_at": "2026-08-31 21:05:00+10:00"}, "fetched_at"),
        ({"http_status": 999}, "http_status"),
        ({"title": "   "}, "title"),
        ({"entities": ["ok", 3]}, "entities"),
    ],
)
def test_bad_records_are_rejected(overrides, expected_fragment):
    errors = validate_record(make_item(**overrides).to_record())
    assert errors, f"expected {overrides} to be rejected"
    assert any(expected_fragment in error for error in errors)


def test_partial_record_reports_every_missing_field():
    errors = validate_record({"id": "x", "source": "gazette"})
    assert len(errors) == len(FIELD_ORDER) - 2


def test_unknown_fields_are_rejected():
    record = make_item().to_record()
    record["value_aud"] = 100
    assert any("unknown field" in error for error in validate_record(record))
    with pytest.raises(SchemaError):
        Item.from_record(record)


def test_source_notes_tokens_round_trip():
    item = make_item(source_notes="")
    item.add_note("kind: special")
    item.add_note("body_pending")
    item.add_note("body_pending")  # adding twice must not duplicate
    assert item.notes == ["kind: special", "body_pending"]
    assert item.has_note("kind") and item.has_note("body_pending")
    assert not item.has_note("no_text_layer")
