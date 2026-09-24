import json
from datetime import date

from rti_tracker.applications import add_event, create, due_deadline_alerts, link_releases, mark_alert_sent, status_for
from rti_tracker.deadlines import EV_ACCEPTED, DeadlineEngine


def _auth(conn):
    conn.execute("INSERT INTO entities(id,kind,name,created_at,updated_at) VALUES ('nre','authority','NRE','x','x')")
    conn.execute("INSERT INTO authorities(id,name,type,rti_status,region) VALUES ('nre','NRE Tas','agency','full','south')")


def test_create_status_and_next_steps(conn):
    _auth(conn)
    app_id = create(conn, authority_id="nre", authority_name=None, lodged=date(2026, 8, 3), accepted=date(2026, 8, 3), scope="STT coupe plans", reference="RTI-26-77")
    st = status_for(conn, app_id, DeadlineEngine(today=date(2026, 8, 10)))
    assert st.state == "awaiting_decision" and st.next_steps
    assert conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()[0] == "awaiting_decision"
    st2 = status_for(conn, app_id, DeadlineEngine(today=date(2026, 9, 24)))
    assert st2.state == "deemed_refused"


def test_link_by_reference_and_scope(conn):
    _auth(conn)
    app_id = create(conn, authority_id="nre", authority_name=None, lodged=date(2026, 8, 1), scope="Correspondence with Trafigura about the Nyrstar smelter grant deed", reference="RTI 2026-27/012")
    conn.execute("INSERT INTO sources(id,authority_id,adapter,url) VALUES (1,'nre','html_table','https://x')")
    conn.execute("INSERT INTO items(source_id,authority_id,external_key,title,reference,fields,fingerprint,first_seen_at,last_seen_at) VALUES (1,'nre','k1','Correspondence re Nyrstar grant','RTI 2026-27/012','{}','f','2026-08-20T00:00:00+00:00','2026-08-20T00:00:00+00:00')")
    conn.execute("INSERT INTO items(source_id,authority_id,external_key,title,reference,fields,fingerprint,first_seen_at,last_seen_at) VALUES (1,'nre','k2','Trafigura Nyrstar smelter grant deed correspondence',NULL,'{}','f','2026-08-21T00:00:00+00:00','2026-08-21T00:00:00+00:00')")
    conn.execute("INSERT INTO items(source_id,authority_id,external_key,title,reference,fields,fingerprint,first_seen_at,last_seen_at) VALUES (1,'nre','k3','Ambulance ramping data',NULL,'{}','f','2026-08-21T00:00:00+00:00','2026-08-21T00:00:00+00:00')")
    props = link_releases(conn, app_id)
    by = {p["matched_by"] for p in props}
    assert "reference" in by and "scope_similarity" in by and len(props) == 2
    assert link_releases(conn, app_id) == []  # idempotent


def test_deadline_alerts_fire_at_offsets_and_dedupe(conn):
    _auth(conn)
    app_id = create(conn, authority_id="nre", authority_name=None, lodged=date(2026, 8, 3), accepted=date(2026, 8, 3), scope="x")
    eng = DeadlineEngine(today=date(2026, 8, 24))  # 5 wd before 31 Aug
    alerts = due_deadline_alerts(conn, eng)
    assert any(a["days_before"] == 5 and a["deadline"].id == "decision_due" for a in alerts)
    for a in alerts:
        mark_alert_sent(conn, a)
    assert due_deadline_alerts(conn, eng) == []
    eng0 = DeadlineEngine(today=date(2026, 8, 31))
    assert any(a["days_before"] == 0 for a in due_deadline_alerts(conn, eng0))
    eng_after = DeadlineEngine(today=date(2026, 9, 1))
    assert any(a["kind"] == "deemed_refusal" for a in due_deadline_alerts(conn, eng_after))
