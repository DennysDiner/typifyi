"""SQLite storage. Items are keyed by a hash of the normalised URL."""

import hashlib
import json
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    url_hash TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    source_id TEXT,
    source_name TEXT,
    tier INTEGER,
    category TEXT,
    paywalled INTEGER DEFAULT 0,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    fulltext TEXT,
    score REAL DEFAULT 0,
    watchlist_hits TEXT,
    salience_hits TEXT,
    duplicate_of INTEGER,
    summary TEXT,
    summarized_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_fetched ON items(fetched_at);

CREATE TABLE IF NOT EXISTS page_links (
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (source_id, url)
);

CREATE TABLE IF NOT EXISTS page_snapshots (
    source_id TEXT PRIMARY KEY,
    content_hash TEXT,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    ok INTEGER NOT NULL,
    status INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_fetch_log_source ON fetch_log(source_id, ts);

CREATE TABLE IF NOT EXISTS alerts_sent (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    rule TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    channel TEXT,
    UNIQUE (item_id, rule)
);
"""

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "smid", "CMP",
}


def normalise_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                       urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalise_url(url).encode("utf-8")).hexdigest()


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_item(conn, **fields) -> int | None:
    """Insert an item; returns row id, or None if URL already known."""
    fields["url_hash"] = url_hash(fields["url"])
    for key in ("watchlist_hits", "salience_hits"):
        if isinstance(fields.get(key), (list, dict)):
            fields[key] = json.dumps(fields[key])
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    try:
        cur = conn.execute(
            f"INSERT INTO items ({cols}) VALUES ({marks})", list(fields.values()))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def log_fetch(conn, source_id: str, ts: str, ok: bool, status=None, error=None):
    conn.execute(
        "INSERT INTO fetch_log (source_id, ts, ok, status, error) VALUES (?, ?, ?, ?, ?)",
        (source_id, ts, 1 if ok else 0, status, error))
    conn.commit()


def source_health(conn) -> list:
    """Per-source: last success, last attempt, last error."""
    rows = conn.execute("""
        SELECT source_id,
               MAX(CASE WHEN ok = 1 THEN ts END) AS last_success,
               MAX(ts) AS last_attempt,
               (SELECT error FROM fetch_log f2 WHERE f2.source_id = f.source_id
                ORDER BY ts DESC LIMIT 1) AS last_error,
               (SELECT ok FROM fetch_log f3 WHERE f3.source_id = f.source_id
                ORDER BY ts DESC LIMIT 1) AS last_ok
        FROM fetch_log f GROUP BY source_id
    """).fetchall()
    return [dict(r) for r in rows]
