"""The Item schema (§2.4) and its validator.

The schema is a contract: adapters emit exactly these fields, records on disk
carry exactly these fields, and anything that fails validation is rejected and
alerted rather than written as a partial row (§5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .timeutil import ISO_LOOSE_RE, ISO_UTC_RE, parse_iso

SOURCES: tuple[str, ...] = ("gazette", "tenders", "contracts", "lobbyists")

FIELD_ORDER: tuple[str, ...] = (
    "id",
    "source",
    "title",
    "published_at",
    "url",
    "body_text",
    "entities",
    "content_hash",
    "fetched_at",
    "http_status",
    "archive_path",
    "source_notes",
)

# Flags are derived, never stored: they are a reading of the record, not a
# separate source of truth that could drift from it.
FLAG_PUBLISHED_AT_MISSING = "published_at_missing"
FLAG_NO_BODY_TEXT = "body_text_empty"
FLAG_NO_ARCHIVE = "archive_missing"

# ``source_notes`` is free text, but a few tokens carry meaning across modules.
# They are written as ``token`` or ``token: detail`` and separated by "; ".
NOTE_BODY_PENDING = "body_pending"
NOTE_NO_TEXT_LAYER = "no_text_layer"
NOTE_BODY_TRUNCATED = "body_truncated_in_record"
NOTE_PUBLISHED_AT_UNSTATED = "published_at_not_stated_by_source"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


class SchemaError(ValueError):
    """Raised when a record cannot be coerced into the Item schema."""


@dataclass
class Item:
    """One normalised record from one source."""

    id: str
    source: str
    title: str
    url: str
    published_at: str | None = None
    body_text: str = ""
    entities: list[str] = field(default_factory=list)
    content_hash: str = ""
    fetched_at: str = ""
    http_status: int | None = None
    archive_path: str | None = None
    source_notes: str = ""

    def to_record(self) -> dict[str, Any]:
        """Serialise in schema order."""
        return {name: getattr(self, name) for name in FIELD_ORDER}

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Item":
        unknown = set(record) - set(FIELD_ORDER)
        if unknown:
            raise SchemaError(f"unknown field(s): {sorted(unknown)}")
        missing = {"id", "source", "title", "url"} - set(record)
        if missing:
            raise SchemaError(f"missing required field(s): {sorted(missing)}")
        return cls(**record)

    @property
    def notes(self) -> list[str]:
        """``source_notes`` split into its ``token`` / ``token: detail`` parts."""
        return [part.strip() for part in self.source_notes.split(";") if part.strip()]

    def has_note(self, token: str) -> bool:
        return any(note == token or note.startswith(token + ":") for note in self.notes)

    def add_note(self, note: str) -> None:
        if note and not self.has_note(note.split(":", 1)[0]):
            self.source_notes = f"{self.source_notes}; {note}".strip("; ").strip()

    @property
    def flags(self) -> list[str]:
        flags: list[str] = []
        if self.published_at is None:
            flags.append(FLAG_PUBLISHED_AT_MISSING)
        if not self.body_text:
            flags.append(FLAG_NO_BODY_TEXT)
        if not self.archive_path:
            flags.append(FLAG_NO_ARCHIVE)
        return flags

    def canonical_fields(self, body_text: str | None = None) -> dict[str, Any]:
        """The fields that define identity of *content* for hashing.

        ``entities``, ``fetched_at``, ``archive_path``, ``http_status`` and
        ``source_notes`` are deliberately excluded: they are run metadata or
        derived locally, and including them would make every run look like a
        change. ``body_text`` may be overridden so that the hash can be taken
        over the full text while the stored record holds a truncated copy.
        """
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "published_at": self.published_at,
            "url": self.url,
            "body_text": self.body_text if body_text is None else body_text,
        }


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return a list of human-readable schema errors (empty means valid)."""
    errors: list[str] = []

    unknown = sorted(set(record) - set(FIELD_ORDER))
    if unknown:
        errors.append(f"unknown field(s): {unknown}")
    for name in FIELD_ORDER:
        if name not in record:
            errors.append(f"missing field: {name}")
    if errors:
        return errors

    def _is_str(name: str, *, allow_empty: bool = False) -> bool:
        value = record[name]
        if not isinstance(value, str):
            errors.append(f"{name}: expected string, got {type(value).__name__}")
            return False
        if not allow_empty and not value.strip():
            errors.append(f"{name}: must not be empty")
            return False
        return True

    _is_str("id")
    _is_str("title")
    _is_str("body_text", allow_empty=True)
    _is_str("source_notes", allow_empty=True)

    if isinstance(record["source"], str):
        if record["source"] not in SOURCES:
            errors.append(f"source: {record['source']!r} not in {list(SOURCES)}")
    else:
        errors.append("source: expected string")

    if _is_str("url") and not _URL_RE.match(record["url"]):
        errors.append(f"url: not an absolute http(s) URL: {record['url']!r}")

    published_at = record["published_at"]
    if published_at is not None:
        if not isinstance(published_at, str):
            errors.append("published_at: expected string or null")
        elif not ISO_LOOSE_RE.match(published_at):
            errors.append(f"published_at: not ISO 8601: {published_at!r}")
        else:
            try:
                parse_iso(published_at)
            except ValueError:
                errors.append(f"published_at: unparseable: {published_at!r}")

    entities = record["entities"]
    if not isinstance(entities, list) or any(not isinstance(e, str) for e in entities):
        errors.append("entities: expected list of strings")

    if not isinstance(record["content_hash"], str) or not _SHA256_RE.match(
        record["content_hash"]
    ):
        errors.append("content_hash: expected lowercase sha256 hex digest")

    fetched_at = record["fetched_at"]
    if not isinstance(fetched_at, str) or not ISO_UTC_RE.match(fetched_at):
        errors.append(f"fetched_at: expected ISO 8601 UTC ending in Z, got {fetched_at!r}")

    status = record["http_status"]
    if status is not None and (not isinstance(status, int) or not 100 <= status <= 599):
        errors.append(f"http_status: expected int 100-599 or null, got {status!r}")

    archive_path = record["archive_path"]
    if archive_path is not None and (
        not isinstance(archive_path, str) or not archive_path.strip()
    ):
        errors.append("archive_path: expected non-empty string or null")

    return errors


def validate_items(items: Iterable[Item]) -> list[tuple[Item, list[str]]]:
    """Validate many items, returning ``(item, errors)`` for the invalid ones."""
    bad: list[tuple[Item, list[str]]] = []
    for item in items:
        errors = validate_record(item.to_record())
        if errors:
            bad.append((item, errors))
    return bad
