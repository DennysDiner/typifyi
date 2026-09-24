import json
from datetime import UTC

from make_pdf import simple_pdf

from rti_tracker.monitor import Monitor
from tests.conftest import fixture_bytes

BASE = "https://example.tas.gov.au"


def _source(conn, adapter="html_table", url="/rti/log", config=None):
    conn.execute("INSERT INTO entities(id,kind,name,created_at,updated_at) VALUES ('t','authority','Test','x','x')")
    conn.execute("INSERT INTO authorities(id,name,type,rti_status,tier) VALUES ('t','Test','agency','full',1)")
    cur = conn.execute("INSERT INTO sources(authority_id,kind,adapter,url,tier,config) VALUES ('t','disclosure_log',?,?,1,?)", (adapter, BASE + url, json.dumps(config or {})))
    return int(cur.lastrowid)


def _setup_table(site):
    site.set("/rti/log", fixture_bytes("table_log.html"))
    site.set("/__data/assets/pdf_file/0011/1234/rti-2026-27-012.pdf", simple_pdf(["Decision letter RTI 2026-27/012", "Released in part under s 37 and s 39"]), content_type="application/pdf")
    site.set("/__data/assets/pdf_file/0011/1235/rti-2026-27-011.pdf", simple_pdf(["Data centre briefing"]), content_type="application/pdf")
    site.set("/rti/releases/2026-27-010", "<html><main><a href='/__data/assets/pdf_file/0011/1240/diary.pdf'>Diary</a></main></html>")
    site.set("/__data/assets/pdf_file/0011/1240/diary.pdf", simple_pdf(["Diary June 2026"]), content_type="application/pdf")


def test_end_to_end_new_unchanged_edit_remove_docchange(conn, fetcher, site):
    _setup_table(site)
    sid = _source(conn)
    mon = Monitor(conn, fetcher)
    rep = mon.poll(sid)
    assert rep.status == "changed" and rep.new_items == 3 and rep.new_documents == 3, rep
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM changes WHERE kind='new_item'").fetchone()[0] == 3
    src = conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
    assert src["last_success_at"] and src["listing_hash"] and src["etag"]

    # second poll: 304 not modified — no new fetches of documents
    n_fetch = conn.execute("SELECT count(*) FROM fetches").fetchone()[0]
    rep2 = mon.poll(sid)
    assert rep2.status == "not_modified"
    assert conn.execute("SELECT count(*) FROM fetches").fetchone()[0] == n_fetch + 1

    # third poll: one item edited (decision changed), one removed (011), one added (013), and doc 012 bytes changed
    site.set("/rti/log", fixture_bytes("table_log_edited.html"))
    site.set("/__data/assets/pdf_file/0011/1234/rti-2026-27-012.pdf", simple_pdf(["Decision letter RTI 2026-27/012 REVISED", "Refused"]), content_type="application/pdf")
    site.set("/__data/assets/pdf_file/0011/1236/rti-2026-27-013.pdf", simple_pdf(["STT coupe plans"]), content_type="application/pdf")
    rep3 = mon.poll(sid)
    assert rep3.status == "changed"
    assert rep3.new_items == 1 and rep3.edited_items == 1 and rep3.removed_items == 1, rep3
    kinds = {r[0] for r in conn.execute("SELECT kind FROM changes")}
    assert {"item_removed", "item_edited", "new_item", "new_document"} <= kinds
    removed = conn.execute("SELECT * FROM items WHERE status='removed'").fetchone()
    assert removed["reference"] == "RTI 2026-27/011" and removed["removed_at"]
    # removal change carries archived document hashes so the copy is retrievable
    rc = json.loads(conn.execute("SELECT detail FROM changes WHERE kind='item_removed'").fetchone()[0])
    assert rc["archived_documents"]
    # edit diff recorded and version history kept
    ec = json.loads(conn.execute("SELECT detail FROM changes WHERE kind='item_edited'").fetchone()[0])
    assert "decision" in ec["diff"] or "Decision" in ec["diff"]
    edited_item = conn.execute("SELECT id FROM items WHERE reference='RTI 2026-27/012'").fetchone()[0]
    assert conn.execute("SELECT count(*) FROM item_versions WHERE item_id=?", (edited_item,)).fetchone()[0] == 2
    # the edited item's document URL was unchanged in the listing so it is NOT refetched by the edit alone
    # (document bytes change detection happens when the item's document list changes or on forced refetch)
    docs012 = conn.execute("SELECT count(*) FROM documents WHERE url LIKE '%012.pdf'").fetchone()[0]
    assert docs012 == 1

    # forced document refetch detects changed bytes, keeps both versions
    n, c = mon.fetch_item_documents(edited_item, [BASE + "/__data/assets/pdf_file/0011/1234/rti-2026-27-012.pdf"], source_id=sid, authority_id="t")
    assert c == 1
    rows = conn.execute("SELECT id, sha256, superseded_by FROM documents WHERE url LIKE '%012.pdf' ORDER BY id").fetchall()
    assert len(rows) == 2 and rows[0]["superseded_by"] == rows[1]["id"] and rows[0]["sha256"] != rows[1]["sha256"]
    assert conn.execute("SELECT count(*) FROM changes WHERE kind='document_changed'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM blobs").fetchone()[0] >= 5


def test_empty_listing_is_error_not_mass_removal(conn, fetcher, site):
    _setup_table(site)
    sid = _source(conn)
    mon = Monitor(conn, fetcher)
    assert mon.poll(sid).status == "changed"
    site.set("/rti/log", "<html><body><p>Site redesign in progress</p></body></html>")
    rep = mon.poll(sid)
    assert rep.status == "error" and "0 items" in (rep.error or "") or "empty" in (rep.error or "")
    assert conn.execute("SELECT count(*) FROM items WHERE status='removed'").fetchone()[0] == 0
    assert conn.execute("SELECT consecutive_failures FROM sources WHERE id=?", (sid,)).fetchone()[0] == 1


def test_blocked_source_flagged(conn, fetcher, site):
    site.set("/rti/log", "forbidden", status=403)
    sid = _source(conn)
    rep = Monitor(conn, fetcher).poll(sid)
    assert rep.status == "blocked"
    assert conn.execute("SELECT blocked FROM sources WHERE id=?", (sid,)).fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM changes WHERE kind='source_blocked'").fetchone()[0] == 1
    # not polled again unless forced
    assert Monitor(conn, fetcher).poll(sid).status == "blocked"


def test_per_release_pages_end_to_end(conn, fetcher, site):
    site.set("/rti/index", fixture_bytes("index_pages.html"))
    site.set("/about/routine-disclosures/right-information/rti-2026-27-021", fixture_bytes("release_page_021.html"))
    site.set("/about/routine-disclosures/right-information/rti-2026-27-020", fixture_bytes("release_page_020.html"))
    for p in ["/sites/default/files/2026-08/rti202627-021_decision.pdf", "/sites/default/files/2026-08/rti202627-021_documents.pdf", "/sites/default/files/2026-08/rti202627-020_decision.pdf"]:
        site.set(p, simple_pdf([p]), content_type="application/pdf")
    sid = _source(conn, adapter="per_release_pages", url="/rti/index", config={"item_selector": "article"})
    rep = Monitor(conn, fetcher).poll(sid)
    assert rep.new_items == 2 and rep.new_documents == 3, rep


def test_adapter_failing_24h_change(conn, fetcher, site):
    from datetime import datetime, timedelta
    _setup_table(site)
    sid = _source(conn)
    mon = Monitor(conn, fetcher)
    mon.poll(sid)
    old = (datetime.now(UTC) - timedelta(hours=30)).replace(microsecond=0).isoformat()
    conn.execute("UPDATE sources SET last_success_at=? WHERE id=?", (old, sid))
    site.set("/rti/log", "boom", status=500)
    mon.poll(sid)
    assert conn.execute("SELECT count(*) FROM changes WHERE kind='adapter_failing'").fetchone()[0] == 1
    mon.poll(sid)  # not duplicated
    assert conn.execute("SELECT count(*) FROM changes WHERE kind='adapter_failing'").fetchone()[0] == 1
    site.set("/rti/log", fixture_bytes("table_log.html"))
    mon.poll(sid)
    assert conn.execute("SELECT count(*) FROM changes WHERE kind='adapter_recovered'").fetchone()[0] == 1
