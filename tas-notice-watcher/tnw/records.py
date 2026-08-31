"""Append-only NDJSON record store (§2.2).

One file per source per month. Records are appended when an item is first seen
or when its content changes: an unchanged item is not rewritten, so the file is
a log of *states*, and the newest line for an id is that item's current state.

``body_text`` in a record may be truncated (the full text is always in the
archived artefact, which is the evidentiary copy); truncation is recorded in
``source_notes`` so no reader can mistake a truncated body for a short one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .models import NOTE_BODY_TRUNCATED, Item, validate_record
from .timeutil import parse_iso

DEFAULT_MAX_BODY_CHARS = 20_000


class RecordValidationError(ValueError):
    def __init__(self, item_id: str, errors: list[str]) -> None:
        super().__init__(f"{item_id}: {'; '.join(errors)}")
        self.item_id = item_id
        self.errors = errors


def month_path(records_dir: Path | str, source: str, when_iso: str) -> Path:
    moment = parse_iso(when_iso)
    return Path(records_dir) / f"{source}-{moment:%Y-%m}.ndjson"


def truncate_body(item: Item, max_chars: int = DEFAULT_MAX_BODY_CHARS) -> Item:
    """Return the item with its stored body bounded (hash is unaffected)."""
    if max_chars <= 0 or len(item.body_text) <= max_chars:
        return item
    item.body_text = item.body_text[:max_chars]
    item.add_note(f"{NOTE_BODY_TRUNCATED}: kept {max_chars} chars, full text in archive")
    return item


def append_items(
    records_dir: Path | str,
    source: str,
    items: Iterable[Item],
    *,
    max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
) -> tuple[int, list[RecordValidationError]]:
    """Append validated items. Invalid records are rejected, never half-written."""
    items = list(items)
    if not items:
        return 0, []

    prepared: list[tuple[Path, str]] = []
    errors: list[RecordValidationError] = []
    for item in items:
        bounded = truncate_body(item, max_body_chars)
        record = bounded.to_record()
        problems = validate_record(record)
        if problems:
            errors.append(RecordValidationError(item.id, problems))
            continue
        prepared.append(
            (
                month_path(records_dir, source, bounded.fetched_at),
                json.dumps(record, ensure_ascii=False, sort_keys=False),
            )
        )

    by_file: dict[Path, list[str]] = {}
    for path, line in prepared:
        by_file.setdefault(path, []).append(line)
    for path, lines in by_file.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return len(prepared), errors


def read_records(records_dir: Path | str, *, sources: Iterable[str] | None = None) -> Iterator[dict]:
    """Yield every record on disk, oldest file first."""
    root = Path(records_dir)
    if not root.exists():
        return
    wanted = set(sources) if sources else None
    for path in sorted(root.glob("*.ndjson")):
        source = path.stem.rsplit("-", 2)[0]
        if wanted and source not in wanted:
            continue
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc


@dataclass
class NearMissWriter:
    """The low-priority review list for fuzzy matches (§4)."""

    path: Path

    def append(self, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)
