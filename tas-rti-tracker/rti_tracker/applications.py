"""Kurt's own RTI applications: logging, events, attachments, deadline computation, auto-linking to
public releases, and deadline alerts. Never exposed publicly."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path

from .archive import Archive
from .db import j, tx, utcnow
from .deadlines import (
    ALL_EVENTS,
    EV_ACCEPTED,
    EV_RECEIVED,
    DeadlineEngine,
    Event,
    Status,
    upcoming_alert_offsets,
)


def create(conn: sqlite3.Connection, *, authority_id: str | None, authority_name: str | None, lodged: date, scope: str,
           reference: str | None = None, fee_amount: float | None = None, fee_waiver: str | None = None,
           accepted: date | None = None, notes: str | None = None) -> int:
    now = utcnow()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO applications(authority_id,authority_name,lodged_date,accepted_date,scope,reference,fee_amount,fee_waiver,status,notes,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,'lodged',?,?,?)",
            (authority_id, authority_name, lodged.isoformat(), accepted.isoformat() if accepted else None, scope, reference, fee_amount, fee_waiver, notes, now, now),
        )
        app_id = int(cur.lastrowid)
        conn.execute("INSERT INTO application_events(application_id,event,event_date,section,detail,recorded_at) VALUES (?,?,?,?,?,?)",
                     (app_id, EV_RECEIVED, lodged.isoformat(), "s 13", "{}", now))
        if accepted:
            conn.execute("INSERT INTO application_events(application_id,event,event_date,section,detail,recorded_at) VALUES (?,?,?,?,?,?)",
                         (app_id, EV_ACCEPTED, accepted.isoformat(), "s 16", "{}", now))
    return app_id


def add_event(conn: sqlite3.Connection, app_id: int, event: str, when: date, detail: dict | None = None, section: str | None = None) -> int:
    if event not in ALL_EVENTS:
        raise ValueError(f"unknown event {event!r}; valid: {ALL_EVENTS}")
    with tx(conn):
        cur = conn.execute("INSERT INTO application_events(application_id,event,event_date,section,detail,recorded_at) VALUES (?,?,?,?,?,?)",
                           (app_id, event, when.isoformat(), section, j(detail or {}), utcnow()))
        if event == EV_ACCEPTED:
            conn.execute("UPDATE applications SET accepted_date=?, updated_at=? WHERE id=?", (when.isoformat(), utcnow(), app_id))
        conn.execute("UPDATE applications SET updated_at=? WHERE id=?", (utcnow(), app_id))
    return int(cur.lastrowid)


def add_attachment(conn: sqlite3.Connection, archive: Archive, app_id: int, path: Path, description: str | None = None) -> str:
    data = path.read_bytes()
    cap = archive.store(data, url=f"file://{path.name}", content_type=None, headers={}, http_status=None, kind="attachment")
    with tx(conn):
        conn.execute("INSERT INTO application_attachments(application_id,filename,sha256,description,added_at) VALUES (?,?,?,?,?)",
                     (app_id, path.name, cap.sha256, description, utcnow()))
    return cap.sha256


def events_for(conn: sqlite3.Connection, app_id: int) -> list[Event]:
    rows = conn.execute("SELECT event, event_date, detail FROM application_events WHERE application_id=? ORDER BY event_date, id", (app_id,)).fetchall()
    return [Event(r["event"], date.fromisoformat(r["event_date"]), json.loads(r["detail"] or "{}")) for r in rows]


def region_for(conn: sqlite3.Connection, authority_id: str | None) -> str | None:
    if not authority_id:
        return None
    r = conn.execute("SELECT region FROM authorities WHERE id=?", (authority_id,)).fetchone()
    return r["region"] if r else None


def status_for(conn: sqlite3.Connection, app_id: int, engine: DeadlineEngine | None = None) -> Status:
    engine = engine or DeadlineEngine()
    app = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
    st = engine.compute(events_for(conn, app_id), region=region_for(conn, app["authority_id"]))
    if app["status"] != st.state:
        conn.execute("UPDATE applications SET status=?, updated_at=? WHERE id=?", (st.state, utcnow(), app_id))
    return st


def refresh_all(conn: sqlite3.Connection, engine: DeadlineEngine | None = None) -> list[tuple[int, Status]]:
    engine = engine or DeadlineEngine()
    out = []
    for r in conn.execute("SELECT id FROM applications WHERE status NOT IN ('closed','withdrawn')"):
        out.append((int(r["id"]), status_for(conn, int(r["id"]), engine)))
    return out


# ---- auto-linking to public releases --------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]{4,}")
STOP = {"information", "documents", "relating", "including", "between", "regarding", "copies", "correspondence", "department", "tasmania", "tasmanian", "records", "about", "under", "with", "from", "that", "this", "which"}


def _tokens(s: str) -> set[str]:
    return {w for w in _WORD.findall((s or "").lower()) if w not in STOP}


def link_releases(conn: sqlite3.Connection, app_id: int | None = None, min_similarity: float = 0.35) -> list[dict]:
    """Match applications to listed items by reference number (high confidence) or scope-word overlap
    (Jaccard on content words, same authority). Links are proposed (confirmed=0) for Kurt to confirm."""
    apps = conn.execute("SELECT * FROM applications" + (" WHERE id=?" if app_id else ""), (app_id,) if app_id else ()).fetchall()
    proposals = []
    for app in apps:
        items = conn.execute("SELECT i.*, (SELECT text FROM document_text t JOIN documents d ON d.id=t.document_id WHERE d.item_id=i.id LIMIT 1) AS text"
                             " FROM items i WHERE (i.authority_id=? OR ? IS NULL) AND i.first_seen_at >= ?",
                             (app["authority_id"], app["authority_id"], app["lodged_date"])).fetchall()
        app_tok = _tokens(app["scope"])
        for it in items:
            if conn.execute("SELECT 1 FROM application_links WHERE application_id=? AND item_id=?", (app["id"], it["id"])).fetchone():
                continue
            matched_by, conf = None, 0.0
            ref = (app["reference"] or "").strip()
            if ref and (ref.lower() in (it["reference"] or "").lower() or ref.lower() in (it["title"] or "").lower() or ref.lower() in (it["text"] or "").lower()[:5000]):
                matched_by, conf = "reference", 0.95
            else:
                it_tok = _tokens((it["title"] or "") + " " + json.dumps(it["fields"] or ""))
                if app_tok and it_tok:
                    sim = len(app_tok & it_tok) / len(app_tok | it_tok)
                    if sim >= min_similarity:
                        matched_by, conf = "scope_similarity", round(sim, 2)
            if matched_by:
                with tx(conn):
                    conn.execute("INSERT INTO application_links(application_id,item_id,matched_by,confidence,linked_at,confirmed) VALUES (?,?,?,?,?,0)",
                                 (app["id"], it["id"], matched_by, conf, utcnow()))
                proposals.append({"application_id": app["id"], "item_id": it["id"], "matched_by": matched_by, "confidence": conf, "title": it["title"]})
    return proposals


# ---- deadline alerts ------------------------------------------------------------------------------
def due_deadline_alerts(conn: sqlite3.Connection, engine: DeadlineEngine, offsets=(5, 2, 0)) -> list[dict]:
    """Deadline alerts that should fire today (N working days before each deadline) and deemed refusals,
    deduplicated via deadline_alerts_sent."""
    out = []
    today = engine.today
    for app_id, st in refresh_all(conn, engine):
        app = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        region = region_for(conn, app["authority_id"])
        for d in st.deadlines:
            if d.id in ("deemed_refusal", "internal_review_deemed_refusal"):
                key = (app_id, d.id, d.due.isoformat(), -1)
                if not conn.execute("SELECT 1 FROM deadline_alerts_sent WHERE application_id=? AND deadline_id=? AND due_date=? AND days_before=?", key).fetchone():
                    out.append({"application_id": app_id, "reference": app["reference"], "authority": app["authority_name"] or app["authority_id"],
                                "kind": "deemed_refusal", "deadline": d, "days_before": -1, "status": st})
                continue
            if "ALTERNATIVE" in d.label:
                continue
            for n, fire_on in upcoming_alert_offsets(engine, d.due, offsets, region).items():
                if fire_on <= today <= d.due or (n == 0 and fire_on == today):
                    key = (app_id, d.id, d.due.isoformat(), n)
                    if conn.execute("SELECT 1 FROM deadline_alerts_sent WHERE application_id=? AND deadline_id=? AND due_date=? AND days_before=?", key).fetchone():
                        continue
                    if fire_on == today:
                        out.append({"application_id": app_id, "reference": app["reference"], "authority": app["authority_name"] or app["authority_id"],
                                    "kind": "deadline", "deadline": d, "days_before": n, "status": st})
    return out


def mark_alert_sent(conn: sqlite3.Connection, alert: dict) -> None:
    d = alert["deadline"]
    with tx(conn):
        conn.execute("INSERT OR IGNORE INTO deadline_alerts_sent(application_id,deadline_id,due_date,days_before,sent_at) VALUES (?,?,?,?,?)",
                     (alert["application_id"], d.id, d.due.isoformat(), alert["days_before"], utcnow()))
