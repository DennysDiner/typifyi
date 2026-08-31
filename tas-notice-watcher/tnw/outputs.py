"""Phase-3/M4 outputs: weekly digest, static Atom feed, NDJSON export.

None of these interpret anything. They re-present records that were already
extracted deterministically, so that the archive, the feed and the digest cannot
disagree with each other.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from .models import FLAG_PUBLISHED_AT_MISSING, Item
from .records import read_records
from .timeutil import utcnow_iso

FEED_ID = "tag:tas-notice-watcher,2026:feed"
ATOM_NS = "http://www.w3.org/2005/Atom"


def recent_records(
    records_dir: Path | str,
    *,
    since: str | None = None,
    sources: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Newest-first records, optionally bounded by fetch time."""
    rows = [
        row
        for row in read_records(records_dir, sources=sources)
        if since is None or row.get("fetched_at", "") >= since
    ]
    rows.sort(key=lambda row: (row.get("fetched_at", ""), row.get("id", "")), reverse=True)
    return rows[:limit] if limit else rows


def latest_by_id(rows: Sequence[dict]) -> list[dict]:
    """Keep only the newest record for each item id (records are a log)."""
    seen: dict[str, dict] = {}
    for row in rows:  # rows are newest-first
        seen.setdefault(f"{row.get('source')}:{row.get('id')}", row)
    return list(seen.values())


def _entry_id(row: dict) -> str:
    return f"tag:tas-notice-watcher,2026:{row.get('source')}:{row.get('id')}:{row.get('content_hash', '')[:16]}"


def render_atom(rows: Sequence[dict], *, title: str = "tas-notice-watcher", self_url: str = "") -> str:
    updated = max((row.get("fetched_at", "") for row in rows), default=utcnow_iso()) or utcnow_iso()
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<feed xmlns="{ATOM_NS}">',
        f"  <title>{escape(title)}</title>",
        f"  <id>{FEED_ID}</id>",
        f"  <updated>{escape(updated)}</updated>",
        '  <generator uri="https://github.com/DennysDiner/typifyi">tas-notice-watcher</generator>',
    ]
    if self_url:
        parts.append(f'  <link rel="self" href="{escape(self_url)}"/>')
    for row in rows:
        published = row.get("published_at")
        entities = ", ".join(row.get("entities") or []) or "none"
        summary_lines = [
            f"source: {row.get('source')}",
            f"stated publication date: {published or 'not stated by source'}",
            f"matched entities: {entities}",
            f"archive: {row.get('archive_path') or 'none'}",
            f"content hash: {row.get('content_hash')}",
        ]
        if row.get("source_notes"):
            summary_lines.append(f"parser notes: {row['source_notes']}")
        parts += [
            "  <entry>",
            f"    <title>{escape(row.get('title') or '(untitled)')}</title>",
            f"    <id>{escape(_entry_id(row))}</id>",
            f"    <updated>{escape(row.get('fetched_at') or updated)}</updated>",
        ]
        if published:
            # Atom wants a full timestamp; a date-only source value is stated as
            # midnight UTC and remains recognisable as date-only in the summary.
            stamp = published if "T" in published else f"{published}T00:00:00Z"
            parts.append(f"    <published>{escape(stamp)}</published>")
        parts += [
            f'    <link rel="alternate" href="{escape(row.get("url") or "")}"/>',
            f'    <category term="{escape(row.get("source") or "")}"/>',
            f"    <summary>{escape(chr(10).join(summary_lines))}</summary>",
            "  </entry>",
        ]
    parts.append("</feed>")
    return "\n".join(parts) + "\n"


def write_feed(
    records_dir: Path | str,
    out_path: Path | str,
    *,
    limit: int = 100,
    self_url: str = "",
) -> Path:
    rows = latest_by_id(recent_records(records_dir))[:limit]
    xml = render_atom(rows, self_url=self_url)
    ET.fromstring(xml)  # fail loudly rather than publish a broken feed
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    return out


def export_ndjson(
    records_dir: Path | str,
    out_path: Path | str,
    *,
    since: str | None = None,
    sources: Iterable[str] | None = None,
) -> tuple[Path, int]:
    rows = recent_records(records_dir, since=since, sources=sources)
    rows.reverse()  # oldest first for a downstream loader
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out, len(rows)


@dataclass
class Digest:
    title: str
    body: str
    item_count: int


def render_digest(rows: Sequence[dict], *, days: int, generated_at: str) -> Digest:
    rows = latest_by_id(rows)
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        by_source.setdefault(row.get("source", "unknown"), []).append(row)

    entity_counts: dict[str, int] = {}
    unstated = 0
    for row in rows:
        for entity in row.get("entities") or []:
            entity_counts[entity] = entity_counts.get(entity, 0) + 1
        if not row.get("published_at"):
            unstated += 1

    lines = [
        f"Digest of the last {days} day(s), generated {generated_at}.",
        "",
        f"- items recorded: **{len(rows)}**",
        f"- items whose source stated no publication date: **{unstated}**",
        "",
    ]
    if entity_counts:
        lines += ["## Watchlist entities seen", ""]
        for entity, count in sorted(entity_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- **{entity}**: {count}")
        lines.append("")

    for source in sorted(by_source):
        source_rows = by_source[source]
        lines += [f"## {source} ({len(source_rows)})", ""]
        for row in sorted(source_rows, key=lambda r: r.get("fetched_at", ""), reverse=True)[:50]:
            published = row.get("published_at") or "date not stated by source"
            entities = ", ".join(row.get("entities") or []) or "no watchlist match"
            lines.append(
                f"- **{row.get('title')}** — {published} — {entities}\n"
                f"  - {row.get('url')}\n"
                f"  - archive: `{row.get('archive_path') or 'none'}`"
            )
        lines.append("")

    lines += [
        "---",
        "Every line above is a deterministic extraction from an archived artefact. "
        "No text in this digest is machine-summarised.",
    ]
    return Digest(
        title=f"[tnw] Weekly digest — {len(rows)} item(s)",
        body="\n".join(lines),
        item_count=len(rows),
    )


def item_to_row(item: Item) -> dict:
    row = item.to_record()
    row["flags"] = item.flags
    return row


def flag_counts(rows: Iterable[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if not row.get("published_at"):
            counts[FLAG_PUBLISHED_AT_MISSING] = counts.get(FLAG_PUBLISHED_AT_MISSING, 0) + 1
    return counts
