"""Per-authority freshness / health check."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta


def health_rows(conn: sqlite3.Connection, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    rows = conn.execute(
        "SELECT a.id AS authority_id, a.name, a.tier, a.disclosure_log_format, a.disclosure_log_url, a.raw,"
        " s.id AS source_id, s.kind, s.adapter, s.url, s.enabled, s.blocked, s.blocked_reason, s.last_fetch_at, s.last_success_at,"
        " s.last_change_at, s.last_status, s.last_error, s.consecutive_failures, s.next_due_at"
        " FROM authorities a LEFT JOIN sources s ON s.authority_id=a.id AND s.kind='disclosure_log' AND s.enabled=1"
        " WHERE a.active=1 AND a.rti_status<>'via_parent' AND a.type<>'business_unit' ORDER BY a.tier, a.name"
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d["source_id"] is None:
            shared = json.loads(r["raw"] or "{}").get("shares_source_with")
            if shared:
                d["state"] = "shared_log"
                d["shares_source_with"] = shared
            elif d["tier"] == 1:
                d["state"] = "TIER1_NO_SOURCE"   # a failure: a priority body is not being monitored at all (audit #1)
            else:
                d["state"] = "no_log" if not d["disclosure_log_url"] or d["disclosure_log_format"] == "none" else "unconfigured"
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
    # adjacent (non-authority) sources and orphaned enabled sources (inactive authorities) — audit #7, #49
    for r in conn.execute(
        "SELECT s.*, a.name AS aname, a.active FROM sources s LEFT JOIN authorities a ON a.id=s.authority_id"
        " WHERE s.enabled=1 AND (s.authority_id IS NULL OR a.active=0 OR s.kind<>'disclosure_log')"):
        d = {"authority_id": r["authority_id"] or f"[{r['kind']}]", "name": r["aname"] or r["kind"], "tier": r["tier"], "disclosure_log_format": None,
             "disclosure_log_url": r["url"], "source_id": r["id"], "kind": r["kind"], "adapter": r["adapter"], "url": r["url"], "enabled": 1,
             "blocked": r["blocked"], "blocked_reason": r["blocked_reason"], "last_fetch_at": r["last_fetch_at"], "last_success_at": r["last_success_at"],
             "last_change_at": r["last_change_at"], "last_status": r["last_status"], "last_error": r["last_error"],
             "consecutive_failures": r["consecutive_failures"], "next_due_at": r["next_due_at"]}
        if r["authority_id"] and r["active"] == 0:
            d["state"] = "ORPHAN_SOURCE_INACTIVE_AUTHORITY"
        elif r["blocked"]:
            d["state"] = "blocked"
        elif r["last_success_at"] is None:
            d["state"] = "never_succeeded" if r["last_fetch_at"] else "never_polled"
        else:
            age = now - datetime.fromisoformat(r["last_success_at"])
            d["state"] = "failing_24h" if age > timedelta(hours=24) else "ok"
        out.append(d)
    return out


FAILURE_STATES = {"TIER1_NO_SOURCE", "ORPHAN_SOURCE_INACTIVE_AUTHORITY", "failing_24h", "blocked", "never_succeeded"}


def has_failures(rows: list[dict]) -> bool:
    return any(r["state"] in FAILURE_STATES for r in rows)


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
