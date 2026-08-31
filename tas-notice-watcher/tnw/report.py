"""Run reporting structures shared by the runner, alerting and summaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .diff import CHANGED, NEW, REMOVED, Change
from .hashing import sha256_text

# Failure kinds. Every one of these must produce a visible FAILURE alert (§5).
FETCH = "fetch"
PARSE = "parse"
CANARY = "canary"
SCHEMA = "schema"
ROBOTS = "robots"
DRIFT = "drift"
STALE = "stale"
INTERNAL = "internal"


@dataclass
class Failure:
    source: str
    kind: str
    message: str
    detail: str = ""

    @property
    def fingerprint(self) -> str:
        """Stable id for de-duplicating recurring failure issues."""
        return sha256_text(f"{self.source}|{self.kind}|{self.message}")[:16]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fingerprint": self.fingerprint}


@dataclass
class SourceReport:
    source: str
    status: str = "skipped"  # ok | failed | skipped
    started_at: str = ""
    duration_s: float = 0.0
    endpoint: str | None = None
    item_count: int = 0
    page_bytes: int = 0
    requests: int = 0
    records_written: int = 0
    near_miss_count: int = 0
    changes: list[Change] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def alertable_changes(self) -> list[Change]:
        return [c for c in self.changes if c.kind in (NEW, CHANGED, REMOVED)]

    @property
    def change_counts(self) -> dict[str, int]:
        result = {NEW: 0, CHANGED: 0, REMOVED: 0}
        for change in self.alertable_changes:
            result[change.kind] += 1
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "started_at": self.started_at,
            "duration_s": round(self.duration_s, 2),
            "endpoint": self.endpoint,
            "item_count": self.item_count,
            "page_bytes": self.page_bytes,
            "requests": self.requests,
            "records_written": self.records_written,
            "near_miss_count": self.near_miss_count,
            "changes": self.change_counts,
            "failures": [f.to_dict() for f in self.failures],
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }


@dataclass
class RunReport:
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0
    slot: str = "manual"
    dry_run: bool = False
    sources: list[SourceReport] = field(default_factory=list)
    global_failures: list[Failure] = field(default_factory=list)

    @property
    def all_failures(self) -> list[Failure]:
        failures = list(self.global_failures)
        for source in self.sources:
            failures.extend(source.failures)
        return failures

    @property
    def all_changes(self) -> list[Change]:
        changes: list[Change] = []
        for source in self.sources:
            changes.extend(source.alertable_changes)
        return changes

    @property
    def ok(self) -> bool:
        return not self.all_failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(self.duration_s, 2),
            "slot": self.slot,
            "dry_run": self.dry_run,
            "ok": self.ok,
            "change_count": len(self.all_changes),
            "failure_count": len(self.all_failures),
            "sources": [s.to_dict() for s in self.sources],
            "global_failures": [f.to_dict() for f in self.global_failures],
        }
