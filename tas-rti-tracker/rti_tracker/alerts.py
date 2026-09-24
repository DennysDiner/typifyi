"""Alert dispatch: immediate alerts for high-value changes and a daily digest for the rest.

Channels: ntfy (RTI_NTFY_URL [+ RTI_NTFY_TOKEN]), email (RTI_SMTP_* + RTI_ALERT_EMAIL_TO), stdout.
Which channel Kurt prefers has not been confirmed (brief §5 says ask); both are implemented and each is
active only when its env vars are set.
"""
from __future__ import annotations

import json
import smtplib
import sqlite3
from email.message import EmailMessage

import httpx

from .config import Settings, settings
from .db import j, tx, utcnow
from .watchlist import scan_change

IMMEDIATE_KINDS = {"item_removed", "item_edited", "document_changed", "item_reappeared", "adapter_failing", "source_blocked"}


def send_ntfy(st: Settings, title: str, body: str, priority: str = "default", tags: list[str] | None = None) -> None:
    if not st.ntfy_url:
        raise RuntimeError("RTI_NTFY_URL not set")
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = ",".join(tags)
    if st.ntfy_token:
        headers["Authorization"] = f"Bearer {st.ntfy_token}"
    httpx.post(st.ntfy_url, content=body.encode(), headers=headers, timeout=30).raise_for_status()


def send_email(st: Settings, subject: str, body: str) -> None:
    if not (st.smtp_host and st.alert_email_to):
        raise RuntimeError("RTI_SMTP_HOST / RTI_ALERT_EMAIL_TO not set")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, st.smtp_user or "rti-tracker@localhost", st.alert_email_to
    msg.set_content(body)
    with smtplib.SMTP(st.smtp_host, st.smtp_port, timeout=30) as s:
        s.starttls()
        if st.smtp_user and st.smtp_password:
            s.login(st.smtp_user, st.smtp_password)
        s.send_message(msg)


def dispatch(conn: sqlite3.Connection, st: Settings, title: str, body: str, *, rule: str, change_id: int | None = None,
             priority: str = "default", channels: list[str] | None = None, dry_run: bool = False) -> list[str]:
    channels = channels or st.alerts.get("channels", ["stdout"])
    sent = []
    for ch in channels:
        cur = conn.execute("INSERT INTO alerts(change_id,channel,rule,payload,status) VALUES (?,?,?,?,'pending')", (change_id, ch, rule, j({"title": title, "body": body})))
        aid = cur.lastrowid
        try:
            if dry_run or ch == "stdout":
                print(f"[alert:{ch}] {title}\n{body}\n")
            elif ch == "ntfy":
                if not st.ntfy_url:
                    conn.execute("UPDATE alerts SET status='skipped', error='channel not configured' WHERE id=?", (aid,))
                    continue
                send_ntfy(st, title, body, priority)
            elif ch == "email":
                if not (st.smtp_host and st.alert_email_to):
                    conn.execute("UPDATE alerts SET status='skipped', error='channel not configured' WHERE id=?", (aid,))
                    continue
                send_email(st, title, body)
            conn.execute("UPDATE alerts SET status='sent', sent_at=? WHERE id=?", (utcnow(), aid))
            sent.append(ch)
        except Exception as e:  # noqa: BLE001
            conn.execute("UPDATE alerts SET status='failed', error=? WHERE id=?", (str(e), aid))
    return sent


def _authority_name(conn, aid):
    r = conn.execute("SELECT name, tier FROM authorities WHERE id=?", (aid,)).fetchone() if aid else None
    return (r["name"], r["tier"]) if r else (aid or "(no authority)", 2)


def process_changes(conn: sqlite3.Connection, st: Settings | None = None, *, dry_run: bool = False) -> dict:
    """Route un-alerted changes: immediate for high-value kinds, Tier 1 new releases and watchlist hits;
    everything else waits for the digest."""
    st = st or settings()
    imm = st.alerts.get("immediate", {})
    counts = {"immediate": 0, "deferred": 0}
    rows = conn.execute("SELECT * FROM changes WHERE alerted_at IS NULL AND digested_at IS NULL ORDER BY id").fetchall()
    for ch in rows:
        name, tier = _authority_name(conn, ch["authority_id"])
        detail = json.loads(ch["detail"] or "{}")
        hits = scan_change(conn, ch) if ch["kind"] in ("new_item", "new_document") and imm.get("watchlist_match", True) else []
        immediate, rule, prio = False, "digest", "default"
        if ch["kind"] in IMMEDIATE_KINDS and imm.get("removal_or_edit", True):
            immediate, rule, prio = True, ch["kind"], "high"
        if ch["kind"] == "adapter_failing" and not imm.get("adapter_failing_24h", True):
            immediate = False
        if ch["kind"] == "new_item" and tier == 1 and imm.get("tier1_new_release", True):
            immediate, rule = True, "tier1_new_release"
        if hits:
            immediate, rule, prio = True, "watchlist_match", "high"
        if immediate:
            title = f"RTI {ch['kind'].replace('_', ' ')}: {name}"
            body = f"{detail.get('title') or ''}\n{detail.get('url') or ''}\n" + (f"campaign hits: {hits}\n" if hits else "") + \
                   (f"diff: {json.dumps(detail.get('diff'))[:800]}\n" if detail.get("diff") else "") + \
                   (f"reason: {detail.get('reason') or detail.get('error') or ''}\n" if detail.get("reason") or detail.get("error") else "") + \
                   f"detected {ch['detected_at']} (change #{ch['id']})"
            dispatch(conn, st, title, body, rule=rule, change_id=ch["id"], priority=prio, dry_run=dry_run)
            conn.execute("UPDATE changes SET alerted_at=? WHERE id=?", (utcnow(), ch["id"]))
            counts["immediate"] += 1
        else:
            counts["deferred"] += 1
    return counts


def send_digest(conn: sqlite3.Connection, st: Settings | None = None, *, dry_run: bool = False) -> int:
    st = st or settings()
    rows = conn.execute("SELECT * FROM changes WHERE digested_at IS NULL ORDER BY authority_id, id").fetchall()
    if not rows:
        return 0
    lines = [f"RTI tracker daily digest — {len(rows)} changes", ""]
    by_auth: dict[str, list] = {}
    for ch in rows:
        by_auth.setdefault(ch["authority_id"] or "(adjacent sources)", []).append(ch)
    for aid, chs in by_auth.items():
        name, _ = _authority_name(conn, aid if aid != "(adjacent sources)" else None)
        lines.append(f"## {name}")
        for ch in chs:
            d = json.loads(ch["detail"] or "{}")
            lines.append(f"- [{ch['kind']}] {d.get('title') or d.get('url') or d.get('error') or ''} ({ch['detected_at'][:10]})")
        lines.append("")
    from .health import health_rows, summary
    lines.append("## Health: " + ", ".join(f"{k}={v}" for k, v in sorted(summary(health_rows(conn)).items())))
    dispatch(conn, st, f"RTI digest: {len(rows)} changes", "\n".join(lines), rule="digest", dry_run=dry_run)
    with tx(conn):
        conn.execute("UPDATE changes SET digested_at=? WHERE digested_at IS NULL", (utcnow(),))
    return len(rows)


def send_deadline_alerts(conn: sqlite3.Connection, st: Settings | None = None, *, dry_run: bool = False) -> int:
    from .applications import due_deadline_alerts, mark_alert_sent
    from .deadlines import DeadlineEngine
    st = st or settings()
    engine = DeadlineEngine()
    offs = tuple(st.alerts.get("deadline_alert_working_days_before", [5, 2, 0]))
    n = 0
    for a in due_deadline_alerts(conn, engine, offs):
        d = a["deadline"]
        if a["kind"] == "deemed_refusal":
            title = f"RTI DEEMED REFUSAL: {a['authority']} {a['reference'] or ''}"
            body = f"{d.display()}\nNext steps:\n" + "\n".join(f"- {s['title']} [{s['section']}]" for s in a["status"].next_steps)
            prio = "high"
        else:
            title = f"RTI deadline in {a['days_before']} working days: {a['authority']} {a['reference'] or ''}"
            body = f"{d.display()}\nState: {a['status'].state} ({a['status'].state_section})"
            prio = "high" if a["days_before"] == 0 else "default"
        dispatch(conn, st, title, body, rule="application_deadline", priority=prio, dry_run=dry_run)
        mark_alert_sent(conn, a)
        n += 1
    return n
