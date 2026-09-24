
from rti_tracker import watchlist
from rti_tracker.alerts import process_changes, send_digest
from rti_tracker.config import Settings, load_yaml
from rti_tracker.registry import coverage_report, load_registry, resolve_authority, sync, validate


def test_registry_valid_and_syncs(conn):
    data = load_registry()
    assert validate(data) == []
    ids = {a["id"] for a in data["authorities"]}
    for must in ["dpac", "treasury", "nre", "justice", "health", "dpfem", "stt", "hydro", "tasnetworks", "tasports", "tasrail", "ttline", "tas_irrigation", "maib", "launceston_cc", "utas", "taswater"]:
        assert must in ids, must
    assert sum(1 for a in data["authorities"] if a["type"] == "council") == 29
    stats = sync(conn, data)
    assert stats["authorities"] == len(data["authorities"])
    # every authority with a disclosure log URL (and not sharing) has exactly one enabled source
    for a in data["authorities"]:
        n = conn.execute("SELECT count(*) FROM sources WHERE authority_id=? AND kind='disclosure_log' AND enabled=1", (a["id"],)).fetchone()[0]
        if a.get("disclosure_log_url") and not a.get("shares_source_with") and a.get("disclosure_log_format") != "none" and a.get("active", True) is not False:
            assert n == 1, a["id"]
        else:
            assert n == 0, a["id"]   # inactive bodies, shared logs and log-less bodies must not be polled (audit #7, #8, #14)
    assert conn.execute("SELECT count(*) FROM sources WHERE authority_id='tlgc' AND enabled=1").fetchone()[0] == 0
    # business units are excluded from health/coverage and never counted as authorities without a log
    from rti_tracker.health import health_rows
    ids = {r["authority_id"] for r in health_rows(conn)}
    assert "ambulance_tas" not in ids and "stt" in ids
    assert any(r["state"] == "TIER1_NO_SOURCE" for r in health_rows(conn) if r["authority_id"] == "stt")
    assert conn.execute("SELECT tier FROM authorities WHERE id='stt'").fetchone()[0] == 1
    assert conn.execute("SELECT tier FROM authorities WHERE id='hobart_cc'").fetchone()[0] == 2
    # historical names resolve by exact match only; loose input yields candidates, never a silent guess
    assert resolve_authority(conn, "Forestry Tasmania") == "stt"
    assert resolve_authority(conn, "Department of State Growth") == "state_growth"
    assert resolve_authority(conn, "Council") is None and resolve_authority(conn, "Tasmania") is None
    assert resolve_authority(conn, "Dept of State Growth", candidates=True)
    rep = coverage_report(data, conn)
    assert "not yet searched" in rep.lower() and "searched, no log found" in rep.lower()


def test_sync_is_idempotent_and_keeps_history(conn):
    data = load_registry()
    sync(conn, data)
    n1 = conn.execute("SELECT count(*) FROM authority_names").fetchone()[0]
    sync(conn, data)
    assert conn.execute("SELECT count(*) FROM authority_names").fetchone()[0] == n1


def test_watchlist_matching_and_citation_pack(conn, archive):
    watchlist.sync(conn, load_yaml(__import__("pathlib").Path("config/watchlist.yaml")))
    hits = watchlist.match_text(conn, "Correspondence with Nyrstar about the smelter")
    assert ("nyrstar", "Nyrstar") in hits
    assert not watchlist.match_text(conn, "STTAS is a substring")  # whole-word: STTAS must not match STT
    conn.execute("INSERT INTO sources(id,adapter,url) VALUES (1,'html_table','https://x')")
    conn.execute("INSERT INTO items(id,source_id,external_key,title,fields,fingerprint,first_seen_at,last_seen_at) VALUES (1,1,'k','Federal Group licence deed','{}','f','t','t')")
    cap = archive.store(b"pdf", url="https://x/d.pdf", content_type="application/pdf", headers={}, http_status=200)
    conn.execute("INSERT INTO documents(id,item_id,url,sha256,capture_id,first_seen_at) VALUES (1,1,'https://x/d.pdf',?,?,'t')", (cap.sha256, cap.id))
    conn.execute("INSERT INTO changes(kind,severity,item_id,document_id,detected_at,detail) VALUES ('new_item','notice',1,1,'t','{}')")
    ch = conn.execute("SELECT * FROM changes").fetchone()
    hits = watchlist.scan_change(conn, ch)
    assert ("pokies", "Federal Group") in hits
    pack = watchlist.citation_pack(conn, "pokies", base_url="http://localhost")
    assert pack and pack[0]["sha256"] == cap.sha256 and pack[0]["source_url"] == "https://x/d.pdf" and pack[0]["retrieved_at"]


def test_alert_routing(conn, capsys, tmp_path):
    st = Settings(db_path=tmp_path / "x.db", archive_dir=tmp_path / "a", alerts={"channels": ["stdout"], "immediate": {}, "digest": {}}, watchlist={"campaigns": []})
    conn.execute("INSERT INTO entities(id,kind,name,created_at,updated_at) VALUES ('t1','authority','T1','x','x'),('t2','authority','T2','x','x')")
    conn.execute("INSERT INTO authorities(id,name,type,rti_status,tier) VALUES ('t1','Tier one','agency','full',1),('t2','Tier two','council','full',2)")
    conn.execute("INSERT INTO changes(kind,severity,authority_id,detected_at,detail) VALUES ('new_item','notice','t1','t','{\"title\":\"A\"}'),('new_item','notice','t2','t','{\"title\":\"B\"}'),('item_removed','high','t2','t','{\"title\":\"C\"}'),('adapter_failing','high','t2','t','{\"error\":\"boom\"}')")
    counts = process_changes(conn, st)
    assert counts == {"immediate": 3, "deferred": 1}
    out = capsys.readouterr().out
    assert "Tier one" in out and "item removed" in out and "adapter failing" in out and "B" not in out
    n = send_digest(conn, st)
    assert n == 4
    assert "B" in capsys.readouterr().out
    assert conn.execute("SELECT count(*) FROM alerts WHERE status='sent'").fetchone()[0] == 4
