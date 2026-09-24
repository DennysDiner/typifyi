"""Per-authority freshness / health check."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone


def health_rows(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT a.id AS authority_id, a.name, a.tier, a.disclosure_log_format, a.disclosure_log_url,"
        " s.id AS source_id, s.kind, s.adapter, s.url, s.enabled, s.blocked, s.blocked_reason, s.last_fetch_at, s.last_success_at,"
        " s.last_change_at, s.last_status, s.last_error, s.consecutive_failures, s.next_due_at"
        " FROM authorities a LEFT JOIN sources s ON s.authority_id=a.id AND s.kind='disclosure_log' AND s.enabled=1"
        " WHERE a.active=1 ORDER BY a.tier, a.name"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d["source_id"] is None:
            d["state"] = "no_log" if d["disclosure_log_format"] in ("none", "unknown", None) and not d["disclosure_log_url"] else "unconfigured"
        elif d["blocked"]:
            d["state"] = "blocked"
        elif d["last_success_at"] is None:
            d["state"] = "never_succeeded" if d["last_fetch_at"] else "never_polled"
        else:
            age = now - datetime.fromisoformat(d["last_success_at"])
            stale_after = timedelta(hours=3 if d["tier"] == 1 else 13)
            if age > timedelta(hours=24):
                d["state"] = "failing_24h"
            elif age > stale_after:
                d["state"] = "stale"
            else:
                d["state"] = "ok"
            d["age_hours"] = round(age.total_seconds() / 3600, 1)
        out.append(d)
    return out


def summary(rows: list[dict]) -> dict[str, int]:
    s: dict[str, int] = {}
    for r in rows:
        s[r["state"]] = s.get(r["state"], 0) + 1
    return s


def format_table(rows: list[dict]) -> str:
    lines = [f"{'authority':40} {'tier':4} {'state':16} {'last_success':20} {'last_change':20} {'fails':5} error"]
    for r in rows:
        lines.append(f"{r['authority_id'][:40]:40} {r['tier']:<4} {r['state']:16} {(r['last_success_at'] or '-')[:19]:20} {(r['last_change_at'] or '-')[:19]:20} {r['consecutive_failures'] if r['consecutive_failures'] is not None else '-':<5} {(r['last_error'] or r['blocked_reason'] or '')[:60]}")
    return "\n".join(lines)
