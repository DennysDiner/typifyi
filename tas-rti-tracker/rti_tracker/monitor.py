"""Poll one source, detect changes, archive new/changed documents, and record change events.

Fingerprints are computed from the LISTING entry (before any per-release page is expanded), so a
release page that gains a document later is only noticed when the listing entry itself changes or on a
forced refetch (`rti poll --force`). Change detection is two-level:
  1. listing level: sha256 over the sorted fingerprints of all parsed items. No diff → nothing to do.
  2. item level: new items, edited items (fingerprint changed → item_versions row), removed items
     (active item absent from the listing → status='removed', removed_at set, high-severity change),
     reappeared items.
Documents are fetched immediately for new items and for items whose document_urls changed. A document
URL that yields different bytes than before gets a new `documents` row linked via superseded_by; the
old blob stays in the archive.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .adapters.base import Adapter, ListedItem, get_adapter
from .db import j, tx, utcnow
from .fetch import Blocked, Fetcher

FAILING_AFTER = timedelta(hours=24)


@dataclass
class PollReport:
    source_id: int
    status: str                       # ok|not_modified|unchanged|changed|error|blocked
    new_items: int = 0
    edited_items: int = 0
    removed_items: int = 0
    reappeared_items: int = 0
    new_documents: int = 0
    changed_documents: int = 0
    error: str | None = None
    item_count: int = 0
    notes: list[str] = field(default_factory=list)


def _record_change(conn: sqlite3.Connection, kind: str, severity: str, *, source_id: int | None = None,
                   authority_id: str | None = None, item_id: int | None = None, document_id: int | None = None,
                   detail: dict | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO changes(kind,severity,source_id,authority_id,item_id,document_id,detected_at,detail)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (kind, severity, source_id, authority_id, item_id, document_id, utcnow(), j(detail or {})),
    )
    return int(cur.lastrowid)


def listing_hash(items: list[ListedItem]) -> str:
    return hashlib.sha256("\n".join(sorted(it.fingerprint() for it in items)).encode()).hexdigest()


class Monitor:
    def __init__(self, conn: sqlite3.Connection, fetcher: Fetcher, *, max_pages: int = 25):
        self.conn = conn
        self.fetcher = fetcher
        self.max_pages = max_pages

    # ------------------------------------------------------------------------------------------
    def poll(self, source_id: int, *, force: bool = False) -> PollReport:
        src = self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if src is None:
            raise KeyError(source_id)
        report = PollReport(source_id=source_id, status="ok")
        if src["blocked"] and not force:
            report.status = "blocked"
            report.error = src["blocked_reason"]
            return report
        config = json.loads(src["config"] or "{}")
        try:
            adapter = get_adapter(src["adapter"])
        except KeyError as e:
            self._fail(src, str(e))
            report.status, report.error = "error", str(e)
            return report
        try:
            items, capture_id, not_modified = self._fetch_listing(src, adapter, config, force)
        except Blocked as e:
            with tx(self.conn):
                self.conn.execute(
                    "UPDATE sources SET blocked=1, blocked_reason=?, last_fetch_at=?, last_status='blocked', last_error=?,"
                    " consecutive_failures=consecutive_failures+1 WHERE id=?",
                    (str(e), utcnow(), str(e), source_id),
                )
                _record_change(self.conn, "source_blocked", "high", source_id=source_id,
                               authority_id=src["authority_id"], detail={"reason": str(e), "url": src["url"]})
            report.status, report.error = "blocked", str(e)
            return report
        except Exception as e:  # noqa: BLE001
            self._fail(src, f"{type(e).__name__}: {e}")
            report.status, report.error = "error", f"{type(e).__name__}: {e}"
            report.notes.append(traceback.format_exc(limit=3))
            return report

        now = utcnow()
        if not_modified:
            with tx(self.conn):
                self._success(src, now)
            report.status = "not_modified"
            return report
        report.item_count = len(items)
        lh = listing_hash(items)
        if lh == src["listing_hash"] and not force:
            with tx(self.conn):
                self._success(src, now)
            report.status = "unchanged"
            return report
        if not items and src["listing_hash"] and not config.get("allow_empty"):
            # A listing that suddenly parses to zero items is far more likely a layout change than a
            # mass removal. Treat as an adapter failure; never mark everything removed.
            self._fail(src, "listing parsed to 0 items (possible layout change); refusing to mark items removed")
            report.status, report.error = "error", "empty listing"
            return report

        with tx(self.conn):
            snap = self.conn.execute(
                "INSERT INTO listing_snapshots(source_id,retrieved_at,listing_hash,item_count,capture_id) VALUES (?,?,?,?,?)",
                (source_id, now, lh, len(items), capture_id),
            )
            snapshot_id = int(snap.lastrowid)
            seen_keys: set[str] = set()
            existing = {r["external_key"]: r for r in self.conn.execute(
                "SELECT * FROM items WHERE source_id=?", (source_id,))}
            to_fetch: list[tuple[int, ListedItem]] = []
            for it in items:
                seen_keys.add(it.external_key)
                fp = it.fingerprint()
                row = existing.get(it.external_key)
                if row is None:
                    if it.page_url and not it.document_urls:
                        try:
                            it = adapter.expand(it, self._page_fetch(src), config)  # fp stays listing-level
                        except Exception as e:  # noqa: BLE001
                            report.notes.append(f"expand failed for {it.page_url}: {e}")
                    cur = self.conn.execute(
                        "INSERT INTO items(source_id,authority_id,external_key,title,url,reference,published_date,decision_date,"
                        "fields,fingerprint,first_seen_at,last_seen_at,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'active')",
                        (source_id, src["authority_id"], it.external_key, it.title, it.url, it.reference, it.published_date,
                         it.decision_date, j({**it.fields, "document_urls": it.document_urls}), fp, now, now),
                    )
                    item_id = int(cur.lastrowid)
                    self.conn.execute(
                        "INSERT INTO item_versions(item_id,seen_at,fingerprint,fields,snapshot_id) VALUES (?,?,?,?,?)",
                        (item_id, now, fp, j({**it.fields, "document_urls": it.document_urls, "title": it.title, "url": it.url}), snapshot_id),
                    )
                    _record_change(self.conn, "new_item", "notice", source_id=source_id, authority_id=src["authority_id"],
                                   item_id=item_id, detail={"title": it.title, "url": it.url, "published_date": it.published_date})
                    report.new_items += 1
                    to_fetch.append((item_id, it))
                else:
                    item_id = int(row["id"])
                    if row["status"] == "removed":
                        self.conn.execute("UPDATE items SET status='active', removed_at=NULL WHERE id=?", (item_id,))
                        _record_change(self.conn, "item_reappeared", "high", source_id=source_id, authority_id=src["authority_id"],
                                       item_id=item_id, detail={"title": it.title, "removed_at": row["removed_at"]})
                        report.reappeared_items += 1
                    if fp != row["fingerprint"]:
                        old_fields = json.loads(row["fields"] or "{}")
                        old_docs = set(old_fields.get("document_urls") or [])
                        if it.page_url and not it.document_urls:
                            try:
                                it = adapter.expand(it, self._page_fetch(src), config)  # fp stays listing-level
                            except Exception as e:  # noqa: BLE001
                                report.notes.append(f"expand failed for {it.page_url}: {e}")
                        new_fields = {**it.fields, "document_urls": it.document_urls}
                        diff = _diff_fields({**old_fields, "title": row["title"], "url": row["url"]},
                                            {**new_fields, "title": it.title, "url": it.url})
                        self.conn.execute(
                            "UPDATE items SET title=?, url=?, reference=?, published_date=?, decision_date=?, fields=?, fingerprint=?,"
                            " last_seen_at=? WHERE id=?",
                            (it.title, it.url, it.reference or row["reference"], it.published_date or row["published_date"],
                             it.decision_date or row["decision_date"], j(new_fields), fp, now, item_id),
                        )
                        self.conn.execute(
                            "INSERT INTO item_versions(item_id,seen_at,fingerprint,fields,snapshot_id) VALUES (?,?,?,?,?)",
                            (item_id, now, fp, j({**new_fields, "title": it.title, "url": it.url}), snapshot_id),
                        )
                        _record_change(self.conn, "item_edited", "high", source_id=source_id, authority_id=src["authority_id"],
                                       item_id=item_id, detail={"title": it.title, "diff": diff})
                        report.edited_items += 1
                        if set(it.document_urls) - old_docs:
                            to_fetch.append((item_id, it))
                    else:
                        self.conn.execute("UPDATE items SET last_seen_at=? WHERE id=?", (now, item_id))
            # removals
            for key, row in existing.items():
                if key not in seen_keys and row["status"] == "active":
                    self.conn.execute("UPDATE items SET status='removed', removed_at=? WHERE id=?", (now, row["id"]))
                    _record_change(self.conn, "item_removed", "high", source_id=source_id, authority_id=src["authority_id"],
                                   item_id=int(row["id"]), detail={"title": row["title"], "url": row["url"],
                                                                   "first_seen_at": row["first_seen_at"],
                                                                   "archived_documents": self._doc_shas(int(row["id"]))})
                    report.removed_items += 1
            self.conn.execute("UPDATE sources SET listing_hash=?, last_change_at=? WHERE id=?", (lh, now, source_id))
            self._success(src, now)
        # Fetch documents outside the listing transaction (each document fetch is its own tx).
        for item_id, it in to_fetch:
            n, c = self.fetch_item_documents(item_id, it.document_urls, source_id=source_id, authority_id=src["authority_id"])
            report.new_documents += n
            report.changed_documents += c
        report.status = "changed"
        return report

    # ------------------------------------------------------------------------------------------
    def _fetch_listing(self, src, adapter: Adapter, config: dict, force: bool):
        url = src["url"]
        etag = None if force else src["etag"]
        lm = None if force else src["last_modified"]
        res = self.fetcher.get(url, source_id=src["id"], etag=etag, last_modified=lm, kind="listing")
        if res.not_modified:
            return [], None, True
        self.conn.execute("UPDATE sources SET etag=?, last_modified=? WHERE id=?", (res.etag, res.last_modified, src["id"]))
        items = adapter.parse(res.body, res.final_url, config)
        capture_id = res.capture.id if res.capture else None
        # pagination
        body, base = res.body, res.final_url
        pages = 1
        seen_urls = {url, res.final_url}
        while pages < self.max_pages:
            nxt = adapter.next_page(body, base, config)
            if not nxt or nxt in seen_urls:
                break
            seen_urls.add(nxt)
            r2 = self.fetcher.get(nxt, source_id=src["id"], kind="listing")
            body, base = r2.body, r2.final_url
            items.extend(adapter.parse(body, base, config))
            pages += 1
        for u in config.get("extra_listing_urls", []):
            r3 = self.fetcher.get(u, source_id=src["id"], kind="listing")
            items.extend(adapter.parse(r3.body, r3.final_url, config))
        return items, capture_id, False

    def _page_fetch(self, src):
        def fetch(url: str) -> bytes:
            r = self.fetcher.get(url, source_id=src["id"], kind="release_page")
            return r.body
        return fetch

    def _doc_shas(self, item_id: int) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT sha256 FROM documents WHERE item_id=?", (item_id,))]

    def fetch_item_documents(self, item_id: int, urls: list[str], *, source_id: int | None, authority_id: str | None) -> tuple[int, int]:
        new = changed = 0
        for u in urls:
            try:
                res = self.fetcher.get(u, source_id=source_id, kind="document")
            except Exception as e:  # noqa: BLE001
                _record_change(self.conn, "document_fetch_failed", "notice", source_id=source_id, authority_id=authority_id,
                               item_id=item_id, detail={"url": u, "error": str(e)})
                continue
            if res.status != 200 or res.capture is None:
                continue
            with tx(self.conn):
                prev = self.conn.execute(
                    "SELECT id, sha256 FROM documents WHERE url=? AND superseded_by IS NULL ORDER BY id DESC LIMIT 1", (u,)
                ).fetchone()
                if prev and prev["sha256"] == res.capture.sha256:
                    continue
                filename = u.split("?")[0].rsplit("/", 1)[-1] or None
                cur = self.conn.execute(
                    "INSERT INTO documents(item_id,authority_id,url,sha256,capture_id,content_type,filename,first_seen_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (item_id, authority_id, u, res.capture.sha256, res.capture.id, res.headers.get("content-type"), filename, res.retrieved_at),
                )
                doc_id = int(cur.lastrowid)
                if prev:
                    self.conn.execute("UPDATE documents SET superseded_by=? WHERE id=?", (doc_id, prev["id"]))
                    _record_change(self.conn, "document_changed", "high", source_id=source_id, authority_id=authority_id,
                                   item_id=item_id, document_id=doc_id,
                                   detail={"url": u, "old_sha256": prev["sha256"], "new_sha256": res.capture.sha256})
                    changed += 1
                else:
                    _record_change(self.conn, "new_document", "notice", source_id=source_id, authority_id=authority_id,
                                   item_id=item_id, document_id=doc_id, detail={"url": u, "sha256": res.capture.sha256})
                    new += 1
        return new, changed

    # ------------------------------------------------------------------------------------------
    def _success(self, src, now: str) -> None:
        was_failing = src["consecutive_failures"] > 0 and src["last_success_at"] and (
            datetime.fromisoformat(now) - datetime.fromisoformat(src["last_success_at"]) > FAILING_AFTER)
        self.conn.execute(
            "UPDATE sources SET last_fetch_at=?, last_success_at=?, last_status='ok', last_error=NULL,"
            " consecutive_failures=0, blocked=0, blocked_reason=NULL WHERE id=?", (now, now, src["id"]),
        )
        if was_failing:
            _record_change(self.conn, "adapter_recovered", "notice", source_id=src["id"], authority_id=src["authority_id"],
                           detail={"failed_since": src["last_success_at"]})

    def _fail(self, src, error: str) -> None:
        now = utcnow()
        with tx(self.conn):
            self.conn.execute(
                "UPDATE sources SET last_fetch_at=?, last_status='error', last_error=?, consecutive_failures=consecutive_failures+1 WHERE id=?",
                (now, error, src["id"]),
            )
            last_ok = src["last_success_at"]
            failing_since = last_ok or src["last_fetch_at"] or now
            over = datetime.fromisoformat(now) - datetime.fromisoformat(failing_since) > FAILING_AFTER
            already = self.conn.execute(
                "SELECT 1 FROM changes WHERE kind='adapter_failing' AND source_id=? AND detected_at > ? LIMIT 1",
                (src["id"], failing_since),
            ).fetchone()
            if over and not already:
                _record_change(self.conn, "adapter_failing", "high", source_id=src["id"], authority_id=src["authority_id"],
                               detail={"error": error, "failing_since": failing_since, "url": src["url"]})


def _diff_fields(old: dict, new: dict) -> dict:
    out: dict = {}
    for k in sorted(set(old) | set(new)):
        if old.get(k) != new.get(k):
            out[k] = {"old": old.get(k), "new": new.get(k)}
    return out
