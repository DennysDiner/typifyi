"""Diffing structured item lists against stored state (§2.3).

Item lists are keyed by ``id``, so reordering a listing page produces no
changes. Removals are only emitted for adapters that see a *complete* listing;
a paginated view that we only partly walked cannot distinguish "gone" from
"on the next page".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .models import NOTE_BODY_PENDING, Item
from .state import ItemState

NEW = "new"
CHANGED = "changed"
REMOVED = "removed"
UNCHANGED = "unchanged"

_TRACKED_FIELDS = ("title", "url", "published_at")


@dataclass
class Change:
    kind: str
    id: str
    title: str
    url: str
    source: str
    item: Item | None = None
    previous: ItemState | None = None
    field_changes: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def is_alertable(self) -> bool:
        return self.kind in (NEW, CHANGED, REMOVED)


def diff_items(
    previous: dict[str, ItemState],
    current: Sequence[Item],
    *,
    source: str,
    detect_removals: bool,
) -> list[Change]:
    """Compare a freshly extracted item list against stored state."""
    changes: list[Change] = []
    seen: set[str] = set()

    for item in current:
        seen.add(item.id)
        before = previous.get(item.id)
        if before is None:
            changes.append(
                Change(kind=NEW, id=item.id, title=item.title, url=item.url,
                       source=item.source, item=item)
            )
            continue
        if before.removed_at:
            changes.append(
                Change(kind=NEW, id=item.id, title=item.title, url=item.url,
                       source=item.source, item=item, previous=before,
                       notes="reappeared after being removed")
            )
            continue
        if before.content_hash != item.content_hash:
            field_changes = []
            for name in _TRACKED_FIELDS:
                old = getattr(before, name)
                new = getattr(item, name)
                if old != new:
                    field_changes.append(f"{name}: {old!r} -> {new!r}")
            if not field_changes:
                field_changes.append("body_text changed")
            if before.body_pending and not item.has_note(NOTE_BODY_PENDING):
                field_changes.append("document text retrieved this run")
            changes.append(
                Change(kind=CHANGED, id=item.id, title=item.title, url=item.url,
                       source=item.source, item=item, previous=before,
                       field_changes=field_changes)
            )
        else:
            changes.append(
                Change(kind=UNCHANGED, id=item.id, title=item.title, url=item.url,
                       source=item.source, item=item, previous=before)
            )

    if detect_removals:
        for item_id, before in previous.items():
            if item_id in seen or before.removed_at:
                continue
            changes.append(
                Change(kind=REMOVED, id=item_id, title=before.title, url=before.url,
                       source=source, previous=before,
                       notes=f"last seen {before.last_seen_at or 'unknown'}")
            )
    return changes


def alertable(changes: Iterable[Change]) -> list[Change]:
    return [change for change in changes if change.is_alertable]


def counts(changes: Iterable[Change]) -> dict[str, int]:
    result = {NEW: 0, CHANGED: 0, REMOVED: 0, UNCHANGED: 0}
    for change in changes:
        result[change.kind] = result.get(change.kind, 0) + 1
    return result
