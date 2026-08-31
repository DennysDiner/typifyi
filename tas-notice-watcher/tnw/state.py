"""Per-source state: the last-seen item index, hashes and HTTP validators (§2.2).

State lives in the repository as JSON so that every change to what the watcher
believes is itself versioned and reviewable.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .timeutil import utcnow_iso

STATE_VERSION = 2
HISTORY_LIMIT = 90


@dataclass
class ItemState:
    """What we knew about one item at the end of the last run."""

    content_hash: str
    title: str
    url: str
    published_at: str | None = None
    archive_path: str | None = None
    first_seen_at: str = ""
    last_seen_at: str = ""
    removed_at: str | None = None
    body_pending: bool = False
    # Hash of the item's row in the listing page. Lets an adapter tell whether a
    # detail page is worth re-fetching without downloading it first.
    listing_hash: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ItemState":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class HttpValidator:
    etag: str | None = None
    last_modified: str | None = None
    fetched_at: str | None = None


@dataclass
class RunHistoryEntry:
    run_at: str
    item_count: int
    page_bytes: int
    status: str


@dataclass
class SourceState:
    source: str
    version: int = STATE_VERSION
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_status: str = "never_run"
    last_error: str | None = None
    consecutive_failures: int = 0
    endpoint: str | None = None  # the listing URL that last worked
    http: dict[str, HttpValidator] = field(default_factory=dict)
    items: dict[str, ItemState] = field(default_factory=dict)
    history: list[RunHistoryEntry] = field(default_factory=list)
    notes: str = ""

    # -- HTTP validators ----------------------------------------------------

    def validator(self, url: str) -> HttpValidator:
        return self.http.get(url, HttpValidator())

    def record_validator(self, url: str, headers: dict[str, str]) -> None:
        lowered = {k.lower(): v for k, v in headers.items()}
        etag = lowered.get("etag")
        last_modified = lowered.get("last-modified")
        if etag or last_modified:
            self.http[url] = HttpValidator(
                etag=etag, last_modified=last_modified, fetched_at=utcnow_iso()
            )

    # -- history ------------------------------------------------------------

    def record_history(self, *, item_count: int, page_bytes: int, status: str, run_at: str | None = None) -> None:
        self.history.append(
            RunHistoryEntry(
                run_at=run_at or utcnow_iso(),
                item_count=item_count,
                page_bytes=page_bytes,
                status=status,
            )
        )
        del self.history[:-HISTORY_LIMIT]

    def prune_removed(self, keep: int = 500) -> None:
        """Keep removed items around (so a removal alerts once) but bounded."""
        removed = [(i, s) for i, s in self.items.items() if s.removed_at]
        if len(removed) <= keep:
            return
        removed.sort(key=lambda pair: pair[1].removed_at or "")
        for item_id, _ in removed[: len(removed) - keep]:
            del self.items[item_id]

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "version": self.version,
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "endpoint": self.endpoint,
            "notes": self.notes,
            "http": {url: asdict(v) for url, v in sorted(self.http.items())},
            "items": {i: asdict(s) for i, s in sorted(self.items.items())},
            "history": [asdict(h) for h in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceState":
        state = cls(source=data["source"])
        state.version = int(data.get("version", STATE_VERSION))
        state.last_attempt_at = data.get("last_attempt_at")
        state.last_success_at = data.get("last_success_at")
        state.last_status = data.get("last_status", "never_run")
        state.last_error = data.get("last_error")
        state.consecutive_failures = int(data.get("consecutive_failures", 0))
        state.endpoint = data.get("endpoint")
        state.notes = data.get("notes", "")
        state.http = {
            url: HttpValidator(**{k: v for k, v in payload.items() if k in HttpValidator.__dataclass_fields__})
            for url, payload in (data.get("http") or {}).items()
        }
        state.items = {
            item_id: ItemState.from_dict(payload)
            for item_id, payload in (data.get("items") or {}).items()
        }
        state.history = [
            RunHistoryEntry(**{k: v for k, v in entry.items() if k in RunHistoryEntry.__dataclass_fields__})
            for entry in (data.get("history") or [])
        ]
        return state


def state_path(state_dir: Path | str, source: str) -> Path:
    return Path(state_dir) / f"{source}.json"


def load_state(state_dir: Path | str, source: str) -> SourceState:
    path = state_path(state_dir, source)
    if not path.exists():
        return SourceState(source=source)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source") != source:
        raise ValueError(f"{path} holds state for {data.get('source')!r}, not {source!r}")
    return SourceState.from_dict(data)


def save_state(state_dir: Path | str, state: SourceState) -> Path:
    path = state_path(state_dir, state.source)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), indent=2, sort_keys=False, ensure_ascii=False)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_json(path: Path | str, default: Any) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path | str, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)
    return path
