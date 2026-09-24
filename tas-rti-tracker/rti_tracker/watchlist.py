"""Campaign keyword watchlist: sync config/watchlist.yaml into `campaigns`, match new items/documents,
auto-tag them, and produce citation packs."""
from __future__ import annotations

import json
import re
import sqlite3

from .db import j, tx, utcnow


def sync(conn: sqlite3.Connection, cfg: dict) -> int:
    n = 0
    with tx(conn):
        for c in cfg.get("campaigns", []):
            conn.execute("INSERT INTO campaigns(id,name,keywords,notes) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, keywords=excluded.keywords",
                         (c["id"], c["name"], j(c.get("keywords") or []), c.get("notes")))
            n += 1
    return n


def _compile(keywords: list[str]) -> re.Pattern:
    parts = [r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])" for k in keywords if k]
    return re.compile("|".join(parts), re.I) if parts else re.compile(r"(?!x)x")


def match_text(conn: sqlite3.Connection, text: str) -> list[tuple[str, str]]:
    """Return [(campaign_id, keyword)] for every campaign with a keyword hit."""
    hits = []
    for c in conn.execute("SELECT id, keywords FROM campaigns"):
        kws = json.loads(c["keywords"] or "[]")
        m = _compile(kws).search(text or "")
        if m:
            hits.append((c["id"], m.group(0)))
    return hits


def tag_item(conn: sqlite3.Connection, campaign_id: str, *, item_id: int | None = None, document_id: int | None = None, by: str = "watchlist", note: str | None = None) -> bool:
    exists = conn.execute("SELECT 1 FROM campaign_tags WHERE campaign_id=? AND COALESCE(item_id,-1)=COALESCE(?,-1) AND COALESCE(document_id,-1)=COALESCE(?,-1)",
                          (campaign_id, item_id, document_id)).fetchone()
    if exists:
        return False
    with tx(conn):
        conn.execute("INSERT INTO campaign_tags(campaign_id,document_id,item_id,tagged_at,tagged_by,note) VALUES (?,?,?,?,?,?)",
                     (campaign_id, document_id, item_id, utcnow(), by, note))
    return True


def scan_change(conn: sqlite3.Connection, change: sqlite3.Row) -> list[tuple[str, str]]:
    """For a new_item / new_document change, match watchlist against title + listing fields + document text."""
    text = ""
    if change["item_id"]:
        it = conn.execute("SELECT title, fields FROM items WHERE id=?", (change["item_id"],)).fetchone()
        if it:
            text += (it["title"] or "") + " " + (it["fields"] or "")
    if change["document_id"]:
        t = conn.execute("SELECT text FROM document_text WHERE document_id=?", (change["document_id"],)).fetchone()
        if t:
            text += " " + t["text"][:200000]
    hits = match_text(conn, text)
    for cid, kw in hits:
        tag_item(conn, cid, item_id=change["item_id"], document_id=change["document_id"], note=f"keyword: {kw}")
    return hits


def citation_pack(conn: sqlite3.Connection, campaign_id: str, base_url: str = "") -> list[dict]:
    rows = conn.execute(
        "SELECT ct.tagged_at, ct.note, d.id AS document_id, d.url, d.sha256, d.first_seen_at, c.retrieved_at, c.http_status, c.final_url, b.path,"
        " i.title, i.published_date, a.name AS authority"
        " FROM campaign_tags ct LEFT JOIN documents d ON d.id=ct.document_id LEFT JOIN captures c ON c.id=d.capture_id"
        " LEFT JOIN blobs b ON b.sha256=d.sha256 LEFT JOIN items i ON i.id=COALESCE(ct.item_id, d.item_id) LEFT JOIN authorities a ON a.id=COALESCE(d.authority_id, i.authority_id)"
        " WHERE ct.campaign_id=? ORDER BY ct.tagged_at", (campaign_id,)).fetchall()
    return [{
        "authority": r["authority"], "title": r["title"], "published_date": r["published_date"], "source_url": r["url"], "final_url": r["final_url"],
        "retrieved_at": r["retrieved_at"], "sha256": r["sha256"], "archived_copy": (f"{base_url}/archive/{r['sha256']}" if r["sha256"] else None),
        "archive_path": r["path"], "tagged_at": r["tagged_at"], "note": r["note"],
    } for r in rows]
