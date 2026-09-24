"""Tiered polling scheduler.

Tier 1 sources are due every `tier1_interval_minutes` (default 60); tier 2 every `tier2_interval_minutes`
(default 360). `run_due()` polls everything due now, spreading requests per host through the Fetcher's
rate limit. Designed to be invoked from cron / systemd timer / GitHub Actions every few minutes; it is
idempotent and cheap when nothing is due. `--loop` runs it forever for a long-lived process.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .db import utcnow
from .monitor import Monitor, PollReport


@dataclass
class SchedulerConfig:
    tier1_interval_minutes: int = 60
    tier2_interval_minutes: int = 360
    failure_backoff_minutes: int = 30
    max_failure_backoff_minutes: int = 720

    @classmethod
    def from_dict(cls, d: dict) -> "SchedulerConfig":
        return cls(
            tier1_interval_minutes=int(d.get("tier1_interval_minutes", 60)),
            tier2_interval_minutes=int(d.get("tier2_interval_minutes", 360)),
            failure_backoff_minutes=int(d.get("failure_backoff_minutes", 30)),
            max_failure_backoff_minutes=int(d.get("max_failure_backoff_minutes", 720)),
        )


def due_sources(conn: sqlite3.Connection, cfg: SchedulerConfig, now: datetime | None = None, tier: int | None = None) -> list[sqlite3.Row]:
    now = now or datetime.now(timezone.utc)
    rows = conn.execute("SELECT * FROM sources WHERE enabled=1 AND blocked=0" + (" AND tier=?" if tier else ""), (tier,) if tier else ()).fetchall()
    due = []
    for r in rows:
        if r["next_due_at"] and datetime.fromisoformat(r["next_due_at"]) > now:
            continue
        if not r["next_due_at"] and r["last_fetch_at"]:
            interval = timedelta(minutes=cfg.tier1_interval_minutes if r["tier"] == 1 else cfg.tier2_interval_minutes)
            if datetime.fromisoformat(r["last_fetch_at"]) + interval > now:
                continue
        due.append(r)
    due.sort(key=lambda r: (r["tier"], r["last_fetch_at"] or ""))
    return due


def schedule_next(conn: sqlite3.Connection, cfg: SchedulerConfig, source_id: int, report: PollReport, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    row = conn.execute("SELECT tier, consecutive_failures FROM sources WHERE id=?", (source_id,)).fetchone()
    base = cfg.tier1_interval_minutes if row["tier"] == 1 else cfg.tier2_interval_minutes
    if report.status in ("error",):
        mins = min(cfg.failure_backoff_minutes * (2 ** max(row["consecutive_failures"] - 1, 0)), cfg.max_failure_backoff_minutes)
        mins = max(mins, base if row["tier"] == 2 else 0)
    else:
        mins = base
    nxt = (now + timedelta(minutes=mins)).replace(microsecond=0).isoformat()
    conn.execute("UPDATE sources SET next_due_at=? WHERE id=?", (nxt, source_id))
    return nxt


def run_due(conn: sqlite3.Connection, monitor: Monitor, cfg: SchedulerConfig, *, tier: int | None = None, limit: int | None = None, force: bool = False) -> list[PollReport]:
    reports: list[PollReport] = []
    rows = conn.execute("SELECT * FROM sources WHERE enabled=1" + (" AND tier=?" if tier else ""), (tier,) if tier else ()).fetchall() if force else due_sources(conn, cfg, tier=tier)
    if limit:
        rows = rows[:limit]
    for r in rows:
        rep = monitor.poll(int(r["id"]), force=force)
        schedule_next(conn, cfg, int(r["id"]), rep)
        reports.append(rep)
    return reports


def loop(conn: sqlite3.Connection, monitor: Monitor, cfg: SchedulerConfig, *, tick_seconds: int = 60, after_tick=None) -> None:
    while True:
        reps = run_due(conn, monitor, cfg)
        if after_tick:
            after_tick(reps)
        time.sleep(tick_seconds)
