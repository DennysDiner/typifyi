"""State persistence and the diff engine (§2.2, §2.3, §7)."""

from __future__ import annotations

from pathlib import Path

from tnw.diff import CHANGED, NEW, REMOVED, UNCHANGED, counts, diff_items
from tnw.models import Item
from tnw.state import HISTORY_LIMIT, ItemState, SourceState, load_state, save_state

NOW = "2026-08-31T21:05:00Z"


def item(item_id: str, *, title="T", url="https://x.tas.gov.au/a", content_hash="1" * 64,
         published_at="2026-08-12", notes="") -> Item:
    return Item(
        id=item_id, source="tenders", title=title, url=url, published_at=published_at,
        content_hash=content_hash, fetched_at=NOW, http_status=200, source_notes=notes,
    )


def state_of(item_id: str, **overrides) -> ItemState:
    base = dict(content_hash="1" * 64, title="T", url="https://x.tas.gov.au/a",
                published_at="2026-08-12", first_seen_at=NOW, last_seen_at=NOW)
    base.update(overrides)
    return ItemState(**base)


def test_new_changed_removed_and_unchanged():
    previous = {
        "a": state_of("a"),
        "b": state_of("b", content_hash="2" * 64),
        "gone": state_of("gone"),
    }
    current = [item("a"), item("b", content_hash="3" * 64, title="T2"), item("c")]
    changes = {c.id: c for c in diff_items(previous, current, source="tenders", detect_removals=True)}

    assert changes["a"].kind == UNCHANGED
    assert changes["b"].kind == CHANGED
    assert "title" in changes["b"].field_changes[0]
    assert changes["c"].kind == NEW
    assert changes["gone"].kind == REMOVED
    assert counts(changes.values())[REMOVED] == 1


def test_reordering_a_listing_produces_no_changes():
    previous = {"a": state_of("a"), "b": state_of("b")}
    forwards = diff_items(previous, [item("a"), item("b")], source="tenders", detect_removals=True)
    backwards = diff_items(previous, [item("b"), item("a")], source="tenders", detect_removals=True)
    assert {c.kind for c in forwards} == {UNCHANGED}
    assert {c.kind for c in backwards} == {UNCHANGED}


def test_removals_are_suppressed_for_partial_listings():
    previous = {"gone": state_of("gone")}
    changes = diff_items(previous, [item("a")], source="contracts", detect_removals=False)
    assert [c.kind for c in changes] == [NEW]


def test_a_removed_item_is_not_reported_twice():
    previous = {"gone": state_of("gone", removed_at=NOW)}
    changes = diff_items(previous, [], source="tenders", detect_removals=True)
    assert changes == []


def test_a_reappearing_item_is_reported_as_new():
    previous = {"back": state_of("back", removed_at=NOW)}
    [change] = diff_items(previous, [item("back")], source="tenders", detect_removals=True)
    assert change.kind == NEW
    assert "reappeared" in change.notes


def test_body_arriving_later_is_explained_in_the_change():
    previous = {"a": state_of("a", body_pending=True, content_hash="9" * 64)}
    [change] = diff_items(previous, [item("a")], source="tenders", detect_removals=False)
    assert change.kind == CHANGED
    assert any("document text retrieved" in entry for entry in change.field_changes)


def test_state_round_trips(tmp_path: Path):
    state = SourceState(source="tenders")
    state.items["a"] = state_of("a")
    state.record_validator("https://x/a", {"ETag": '"abc"', "Last-Modified": "Mon, 31 Aug 2026 00:00:00 GMT"})
    state.record_history(item_count=3, page_bytes=1000, status="ok", run_at=NOW)
    state.last_success_at = NOW
    save_state(tmp_path, state)

    loaded = load_state(tmp_path, "tenders")
    assert loaded.items["a"].content_hash == "1" * 64
    assert loaded.validator("https://x/a").etag == '"abc"'
    assert loaded.history[-1].item_count == 3
    assert loaded.last_success_at == NOW


def test_unknown_source_state_is_empty(tmp_path: Path):
    assert load_state(tmp_path, "gazette").last_status == "never_run"


def test_history_is_bounded(tmp_path: Path):
    state = SourceState(source="tenders")
    for index in range(HISTORY_LIMIT + 25):
        state.record_history(item_count=index, page_bytes=1, status="ok", run_at=NOW)
    assert len(state.history) == HISTORY_LIMIT
    assert state.history[-1].item_count == HISTORY_LIMIT + 24


def test_removed_items_are_pruned_but_live_ones_are_kept():
    state = SourceState(source="tenders")
    for index in range(600):
        state.items[f"r{index}"] = state_of(f"r{index}", removed_at=f"2026-01-01T00:{index % 60:02d}:00Z")
    state.items["live"] = state_of("live")
    state.prune_removed(keep=100)
    assert "live" in state.items
    assert sum(1 for s in state.items.values() if s.removed_at) == 100
