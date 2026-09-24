"""Poll one source, detect changes, archive new/changed documents, and record change events.

Change detection is two-level:
  1. listing level: sha256 over the sorted fingerprints of all parsed items. No diff → nothing to do
     except refreshing `items.last_seen_at` / `last_capture_id` for every listed item.
  2. item level: new items, edited items (fingerprint changed → item_versions row), removed items,
     reappeared items.

Removal rules (audit findings 31, 37, 39):
  - a removal is only counted on a COMPLETE crawl (all pagination followed within max_pages); a truncated
    crawl never marks anything removed;
  - an entry must be missing from `removal_confirm_polls` consecutive complete polls (default 2) before it
    is recorded as removed, so a transient page glitch does not produce a false "silent removal" claim;
  - the removal change carries the id of the last listing capture that still contained the entry and the
    capture that first lacked it (before/after evidence), plus the archived document hashes;
  - a removal that coincides with a similar-titled new entry in the same poll is labelled a
    `possible_replacement` rather than a bare removal.

Fingerprints are computed from the LISTING entry (before any per-release page is expanded). Document bytes
are re-checked by `recheck_documents()` (conditional GET, re-hash) on a schedule, because a PDF replaced at
the same URL does not change the listing (finding 34). ETag/Last-Modified are stored only after a
successful parse, so a 304 can never mask a broken parser (finding 35).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import sqlite3
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .adapters.base import Adapter, ListedItem, get_adapter
from .db import j, tx, utcnow
from .fetch import Blocked, Fetcher, FetchError

FAILING_AFTER = timedelta(hours=24)
DEFAULT_REMOVAL_CONFIRM_POLLS = 2


@dataclass
class PollReport:
    source_id: int
    status: str                       # ok|not_modified|unchanged|changed|error|blocked
    new_items: int = 0
    edited_items: int = 0
    removed_items: int = 0
    pending_removals: int = 0
    reappeared_items: int = 0
    new_documents: int = 0
    changed_documents: int = 0
    error: str | None = None
    item_count: int = 0
    complete: bool = True
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


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


class Monitor:
    def __init__(self, conn: sqlite3.Connection, fetcher: Fetcher, *, max_pages: int = 25,
                 removal_confirm_polls: int = DEFAULT_REMOVAL_CONFIRM_POLLS):
        self.conn = conn
        self.fetcher = fetcher
        self.max_pages = max_pages
        self.removal_confirm_polls = removal_confirm_polls

    # ------------------------------------------------------------------------------------------
    def poll(self, source_id: int, *, force: bool = False) -> PollReport:
        try:
            return self._poll(source_id, force=force)
        except Exception as e:  # noqa: BLE001 — never let one source abort the whole tick
            src = self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            if src is not None:
                self._fail(src, f"internal error: {type(e).__name__}: {e}")
            rep = PollReport(source_id=source_id, status="error", error=f"{type(e).__name__}: {e}")
            rep.notes.append(traceback.format_exc(limit=5))
            return rep

    def _poll(self, source_id: int, *, force: bool) -> PollReport:
        src = self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if src is None:
            raise KeyError(source_id)
        report = PollReport(source_id=source_id, status="ok")
        if src["blocked"] and not force:
            report.status, report.error = "blocked", src["blocked_reason"]
            return report
        config = json.loads(src["config"] or "{}")
        if src["detected_format"] and src["adapter"] == "auto":
            config["pinned_format"] = src["detected_format"]
        try:
            adapter = get_adapter(src["adapter"])
        except KeyError as e:
            self._fail(src, str(e))
            report.status, report.error = "error", str(e)
            return report
        try:
            items, capture_ids, not_modified, complete, etag, last_modified = self._fetch_listing(src, adapter, config, force)
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
        except (FetchError, Exception) as e:  # noqa: BLE001
            self._fail(src, f"{type(e).__name__}: {e}")
            report.status, report.error = "error", f"{type(e).__name__}: {e}"
            return report

        now = utcnow()
        report.complete = complete
        if not_modified:
            with tx(self.conn):
                # 304: the listing is byte-identical to the last fetch, so everything listed then is still
                # listed (last_seen_at moves) and everything pending removal is still missing.
                self.conn.execute("UPDATE items SET last_seen_at=? WHERE source_id=? AND status='active' AND missing_polls=0", (now, src["id"]))
                pending = {r["external_key"]: r for r in self.conn.execute(
                    "SELECT * FROM items WHERE source_id=? AND status='active' AND missing_polls>0", (src["id"],))}
                last_snap = self.conn.execute("SELECT complete FROM listing_snapshots WHERE source_id=? ORDER BY id DESC LIMIT 1", (src["id"],)).fetchone()
                report.removed_items, report.pending_removals = self._process_removals(
                    src, pending, set(), bool(last_snap["complete"]) if last_snap else False, None, now, [], config, report)
                self._success(src, now)
            report.status = "not_modified"
            return report
        report.item_count = len(items)
        if not items and not config.get("allow_empty"):
            # Zero items (first poll or later) is far more likely a wrong URL / layout change than an empty
            # log. Never treat it as success, never mark anything removed.
            self._fail(src, "listing parsed to 0 items (wrong URL or layout change?); refusing to treat as success")
            report.status, report.error = "error", "empty listing"
            return report
        # auto adapter: persist / pin detected format, alert if it switches (finding 36)
        detected = config.get("detected_format")
        if src["adapter"] == "auto" and detected:
            if src["detected_format"] and src["detected_format"] != detected:
                _record_change(self.conn, "adapter_format_switched", "high", source_id=source_id, authority_id=src["authority_id"],
                               detail={"from": src["detected_format"], "to": detected, "note": "external keys may change; removals suppressed this poll"})
                complete = False  # suppress removals on a format switch
            self.conn.execute("UPDATE sources SET detected_format=? WHERE id=?", (detected, source_id))
        lh = listing_hash(items)
        first_capture = capture_ids[0] if capture_ids else None
        if lh == src["listing_hash"] and not force:
            with tx(self.conn):
                keys = {it.external_key for it in items}
                existing = {r["external_key"]: r for r in self.conn.execute("SELECT * FROM items WHERE source_id=?", (source_id,))}
                if keys:
                    marks = ",".join("?" * len(keys))
                    self.conn.execute(f"UPDATE items SET last_seen_at=?, missing_polls=0, last_capture_id=? WHERE source_id=? AND status='active' AND external_key IN ({marks})",
                                      (now, first_capture, source_id, *keys))
                report.removed_items, report.pending_removals = self._process_removals(
                    src, existing, keys, complete, first_capture, now, [], config, report)
                self._save_validators(src, etag, last_modified)
                self._success(src, now)
            report.status = "unchanged"
            return report

        with tx(self.conn):
            snap = self.conn.execute(
                "INSERT INTO listing_snapshots(source_id,retrieved_at,listing_hash,item_count,capture_id,complete,capture_ids) VALUES (?,?,?,?,?,?,?)",
                (source_id, now, lh, len(items), first_capture, 1 if complete else 0, j(capture_ids)),
            )
            snapshot_id = int(snap.lastrowid)
            seen_keys: set[str] = set()
            existing = {r["external_key"]: r for r in self.conn.execute("SELECT * FROM items WHERE source_id=?", (source_id,))}
            to_fetch: list[tuple[int, ListedItem]] = []
            new_titles: list[tuple[int, str]] = []
            for it in items:
                seen_keys.add(it.external_key)
                fp = it.fingerprint()
                row = existing.get(it.external_key)
                authority_id = self._attribute(src, it, config)
                if row is None:
                    if it.page_url and not it.document_urls:
                        try:
                            it = adapter.expand(it, self._page_fetch(src), config)  # fp stays listing-level
                        except Exception as e:  # noqa: BLE001
                            report.notes.append(f"expand failed for {it.page_url}: {e}")
                    cur = self.conn.execute(
                        "INSERT INTO items(source_id,authority_id,external_key,title,url,reference,published_date,decision_date,"
                        "fields,fingerprint,first_seen_at,last_seen_at,status,missing_polls,last_capture_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'active',0,?)",
                        (source_id, authority_id, it.external_key, it.title, it.url, it.reference, it.published_date,
                         it.decision_date, j({**it.fields, "document_urls": it.document_urls}), fp, now, now, first_capture),
                    )
                    item_id = int(cur.lastrowid)
                    self.conn.execute(
                        "INSERT INTO item_versions(item_id,seen_at,fingerprint,fields,snapshot_id) VALUES (?,?,?,?,?)",
                        (item_id, now, fp, j({**it.fields, "document_urls": it.document_urls, "title": it.title, "url": it.url}), snapshot_id),
                    )
                    _record_change(self.conn, "new_item", "notice", source_id=source_id, authority_id=authority_id,
                                   item_id=item_id, detail={"title": it.title, "url": it.url, "published_date": it.published_date,
                                                            "listing_capture_id": first_capture})
                    report.new_items += 1
                    new_titles.append((item_id, it.title))
                    to_fetch.append((item_id, it))
                else:
                    item_id = int(row["id"])
                    if row["status"] == "removed":
                        self.conn.execute("UPDATE items SET status='active', removed_at=NULL WHERE id=?", (item_id,))
                        _record_change(self.conn, "item_reappeared", "high", source_id=source_id, authority_id=row["authority_id"],
                                       item_id=item_id, detail={"title": it.title, "removed_at": row["removed_at"], "listing_capture_id": first_capture})
                        report.reappeared_items += 1
                    if fp != row["fingerprint"]:
                        old_fields = json.loads(row["fields"] or "{}")
                        old_docs = set(old_fields.get("document_urls") or [])
                        if it.page_url and not it.document_urls:
                            try:
                                it = adapter.expand(it, self._page_fetch(src), config)
                            except Exception as e:  # noqa: BLE001
                                report.notes.append(f"expand failed for {it.page_url}: {e}")
                        new_fields = {**it.fields, "document_urls": it.document_urls}
                        diff = _diff_fields({**old_fields, "title": row["title"], "url": row["url"]},
                                            {**new_fields, "title": it.title, "url": it.url})
                        self.conn.execute(
                            "UPDATE items SET title=?, url=?, reference=?, published_date=?, decision_date=?, fields=?, fingerprint=?,"
                            " last_seen_at=?, missing_polls=0, last_capture_id=? WHERE id=?",
                            (it.title, it.url, it.reference or row["reference"], it.published_date or row["published_date"],
                             it.decision_date or row["decision_date"], j(new_fields), fp, now, first_capture, item_id),
                        )
                        self.conn.execute(
                            "INSERT INTO item_versions(item_id,seen_at,fingerprint,fields,snapshot_id) VALUES (?,?,?,?,?)",
                            (item_id, now, fp, j({**new_fields, "title": it.title, "url": it.url}), snapshot_id),
                        )
                        _record_change(self.conn, "item_edited", "high", source_id=source_id, authority_id=row["authority_id"],
                                       item_id=item_id, detail={"title": it.title, "diff": diff, "before_capture_id": row["last_capture_id"],
                                                                "after_capture_id": first_capture})
                        report.edited_items += 1
                        if set(it.document_urls) - old_docs:
                            to_fetch.append((item_id, it))
                    else:
                        self.conn.execute("UPDATE items SET last_seen_at=?, missing_polls=0, last_capture_id=? WHERE id=?", (now, first_capture, item_id))
            report.removed_items, report.pending_removals = self._process_removals(
                src, existing, seen_keys, complete, first_capture, now, new_titles, config, report)
            self.conn.execute("UPDATE sources SET listing_hash=?, last_change_at=? WHERE id=?", (lh, now, source_id))
            self._save_validators(src, etag, last_modified)
            self._success(src, now)
        for item_id, it in to_fetch:
            n, c = self.fetch_item_documents(item_id, it.document_urls, source_id=source_id, authority_id=src["authority_id"])
            report.new_documents += n
            report.changed_documents += c
        report.status = "changed"
        return report

    # ------------------------------------------------------------------------------------------
    def _process_removals(self, src, existing: dict, seen_keys: set, complete: bool, first_capture, now: str,
                          new_titles: list, config: dict, report: PollReport) -> tuple[int, int]:
        """Only on a complete crawl, only after N consecutive misses; carries before/after capture ids."""
        removed = pending = 0
        confirm = int(config.get("removal_confirm_polls", self.removal_confirm_polls))
        for key, row in existing.items():
            if key in seen_keys or row["status"] != "active":
                continue
            if not complete:
                report.notes.append(f"crawl truncated; not counting '{row['title']}' as missing")
                continue
            missing = int(row["missing_polls"] or 0) + 1
            if missing < confirm:
                self.conn.execute("UPDATE items SET missing_polls=? WHERE id=?", (missing, row["id"]))
                pending += 1
                continue
            self.conn.execute("UPDATE items SET status='removed', removed_at=?, missing_polls=? WHERE id=?", (now, missing, row["id"]))
            replacement = None
            for nid, ntitle in new_titles:
                if _similar(row["title"], ntitle) >= 0.6:
                    replacement = {"item_id": nid, "title": ntitle, "similarity": round(_similar(row["title"], ntitle), 2)}
                    break
            _record_change(self.conn, "item_removed", "high" if not replacement else "notice", source_id=src["id"],
                           authority_id=row["authority_id"], item_id=int(row["id"]),
                           detail={"title": row["title"], "url": row["url"], "first_seen_at": row["first_seen_at"],
                                   "last_seen_at": row["last_seen_at"], "last_capture_with_entry": row["last_capture_id"],
                                   "first_capture_without_entry": first_capture, "missing_polls": missing,
                                   "possible_replacement": replacement, "archived_documents": self._doc_shas(int(row["id"]))})
            removed += 1
        return removed, pending

    def _fetch_listing(self, src, adapter: Adapter, config: dict, force: bool):
        url = src["url"]
        etag = None if force else src["etag"]
        lm = None if force else src["last_modified"]
        res = self.fetcher.get(url, source_id=src["id"], etag=etag, last_modified=lm, kind="listing")
        if res.not_modified:
            return [], [], True, True, src["etag"], src["last_modified"]
        items = adapter.parse(res.body, res.final_url, config)
        capture_ids = [res.capture.id] if res.capture else []
        body, base = res.body, res.final_url
        pages, complete = 1, True
        seen_urls = {url, res.final_url}
        while True:
            nxt = adapter.next_page(body, base, config)
            if not nxt or nxt in seen_urls:
                break
            if pages >= self.max_pages:
                complete = False  # truncated: removals must not be inferred from this crawl
                break
            seen_urls.add(nxt)
            r2 = self.fetcher.get(nxt, source_id=src["id"], kind="listing")
            body, base = r2.body, r2.final_url
            items.extend(adapter.parse(body, base, config))
            if r2.capture:
                capture_ids.append(r2.capture.id)
            pages += 1
        for u in config.get("extra_listing_urls", []):
            r3 = self.fetcher.get(u, source_id=src["id"], kind="listing")
            items.extend(adapter.parse(r3.body, r3.final_url, config))
            if r3.capture:
                capture_ids.append(r3.capture.id)
        return items, capture_ids, False, complete, res.etag, res.last_modified

    def _save_validators(self, src, etag, last_modified) -> None:
        self.conn.execute("UPDATE sources SET etag=?, last_modified=? WHERE id=?", (etag, last_modified, src["id"]))

    def _attribute(self, src, it: ListedItem, config: dict) -> str | None:
        """Attribute an entry to a specific authority when the source is shared (e.g. DPAC's ministerial
        log): config.attribution = 'authority_names' matches known names/aliases in the entry text."""
        if config.get("attribution") != "authority_names":
            return src["authority_id"]
        text = " ".join([it.title or "", json.dumps(it.fields, ensure_ascii=False)]).lower()
        best = None
        for r in self.conn.execute("SELECT n.authority_id, n.name FROM authority_names n JOIN authorities a ON a.id=n.authority_id"
                                   " WHERE (? IS NULL OR a.type=?) ORDER BY length(n.name) DESC", (config.get("attribution_type"), config.get("attribution_type"))):
            nm = r["name"].lower()
            for token in [nm] + [t for t in nm.replace(",", " ").split() if len(t) > 4 and t not in ("minister", "premier", "deputy", "former", "treasurer")]:
                if token in text:
                    best = r["authority_id"]
                    break
            if best:
                break
        return best or src["authority_id"]

    def _page_fetch(self, src):
        def fetch(url: str) -> bytes:
            r = self.fetcher.get(url, source_id=src["id"], kind="release_page")
            return r.body
        return fetch

    def _doc_shas(self, item_id: int) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT sha256 FROM documents WHERE item_id=?", (item_id,))]

    # ------------------------------------------------------------------------------------------
    def fetch_item_documents(self, item_id: int, urls: list[str], *, source_id: int | None, authority_id: str | None) -> tuple[int, int]:
        new = changed = 0
        for u in urls:
            try:
                res = self.fetcher.get(u, source_id=source_id, kind="document")
            except FetchError as e:
                with tx(self.conn):
                    kind = "document_unavailable" if e.status in (404, 410) else "document_fetch_failed"
                    _record_change(self.conn, kind, "high" if kind == "document_unavailable" else "notice", source_id=source_id,
                                   authority_id=authority_id, item_id=item_id, detail={"url": u, "error": str(e), "status": e.status,
                                                                                       "archived_documents": self._doc_shas(item_id)})
                continue
            except Exception as e:  # noqa: BLE001
                with tx(self.conn):
                    _record_change(self.conn, "document_fetch_failed", "notice", source_id=source_id, authority_id=authority_id,
                                   item_id=item_id, detail={"url": u, "error": str(e)})
                continue
            if res.status != 200 or res.capture is None:
                continue
            with tx(self.conn):
                n, c = self._record_document(item_id, u, res, source_id=source_id, authority_id=authority_id)
                new += n
                changed += c
        return new, changed

    def _record_document(self, item_id: int | None, u: str, res, *, source_id, authority_id) -> tuple[int, int]:
        current = self.conn.execute(
            "SELECT id, sha256 FROM documents WHERE url=? AND superseded_by IS NULL ORDER BY id DESC LIMIT 1", (u,)).fetchone()
        if current and current["sha256"] == res.capture.sha256:
            return 0, 0
        earlier = self.conn.execute("SELECT id FROM documents WHERE url=? AND sha256=?", (u, res.capture.sha256)).fetchone()
        if earlier:
            # Revert to a version seen before: reinstate that row as current rather than violating UNIQUE(url, sha256).
            self.conn.execute("UPDATE documents SET superseded_by=NULL WHERE id=?", (earlier["id"],))
            if current:
                self.conn.execute("UPDATE documents SET superseded_by=? WHERE id=?", (earlier["id"], current["id"]))
            _record_change(self.conn, "document_reverted", "high", source_id=source_id, authority_id=authority_id, item_id=item_id,
                           document_id=int(earlier["id"]), detail={"url": u, "reverted_to_sha256": res.capture.sha256,
                                                                   "from_sha256": current["sha256"] if current else None,
                                                                   "capture_id": res.capture.id})
            return 0, 1
        filename = u.split("?")[0].rsplit("/", 1)[-1] or None
        cur = self.conn.execute(
            "INSERT INTO documents(item_id,authority_id,url,sha256,capture_id,content_type,filename,first_seen_at) VALUES (?,?,?,?,?,?,?,?)",
            (item_id, authority_id, u, res.capture.sha256, res.capture.id, res.headers.get("content-type"), filename, res.retrieved_at),
        )
        doc_id = int(cur.lastrowid)
        if current:
            self.conn.execute("UPDATE documents SET superseded_by=? WHERE id=?", (doc_id, current["id"]))
            _record_change(self.conn, "document_changed", "high", source_id=source_id, authority_id=authority_id, item_id=item_id,
                           document_id=doc_id, detail={"url": u, "old_sha256": current["sha256"], "new_sha256": res.capture.sha256,
                                                       "old_document_id": current["id"], "capture_id": res.capture.id})
            return 0, 1
        _record_change(self.conn, "new_document", "notice", source_id=source_id, authority_id=authority_id, item_id=item_id,
                       document_id=doc_id, detail={"url": u, "sha256": res.capture.sha256, "capture_id": res.capture.id})
        return 1, 0

    def recheck_documents(self, source_id: int, *, max_docs: int = 200) -> dict:
        """Re-fetch every current document of a source with a conditional GET and re-hash. Detects replaced
        (re-redacted) files at the same URL, reverts and 404s. Cheap when servers honour ETag/Last-Modified."""
        src = self.conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        docs = self.conn.execute(
            "SELECT d.id, d.item_id, d.url, d.sha256, c.headers FROM documents d JOIN captures c ON c.id=d.capture_id"
            " WHERE d.superseded_by IS NULL AND d.item_id IN (SELECT id FROM items WHERE source_id=?) ORDER BY d.id LIMIT ?",
            (source_id, max_docs)).fetchall()
        out = {"checked": 0, "unchanged": 0, "changed": 0, "unavailable": 0, "errors": 0}
        for d in docs:
            hdrs = json.loads(d["headers"] or "{}")
            out["checked"] += 1
            try:
                res = self.fetcher.get(d["url"], source_id=source_id, etag=hdrs.get("etag"), last_modified=hdrs.get("last-modified"), kind="document")
            except FetchError as e:
                with tx(self.conn):
                    if e.status in (404, 410):
                        out["unavailable"] += 1
                        already = self.conn.execute("SELECT 1 FROM changes WHERE kind='document_unavailable' AND document_id=?", (d["id"],)).fetchone()
                        if not already:
                            _record_change(self.conn, "document_unavailable", "high", source_id=source_id, authority_id=src["authority_id"],
                                           item_id=d["item_id"], document_id=d["id"], detail={"url": d["url"], "status": e.status, "archived_sha256": d["sha256"]})
                    else:
                        out["errors"] += 1
                continue
            except Exception:  # noqa: BLE001
                out["errors"] += 1
                continue
            if res.not_modified or (res.capture and res.capture.sha256 == d["sha256"]):
                out["unchanged"] += 1
                continue
            if res.capture:
                with tx(self.conn):
                    _, c = self._record_document(d["item_id"], d["url"], res, source_id=source_id, authority_id=src["authority_id"])
                out["changed"] += c
        self.conn.execute("UPDATE sources SET last_doc_recheck_at=? WHERE id=?", (utcnow(), source_id))
        return out

    # ------------------------------------------------------------------------------------------
    def _success(self, src, now: str) -> None:
        was_failing = bool(src["failing_since"]) and (
            datetime.fromisoformat(now) - datetime.fromisoformat(src["failing_since"]) > FAILING_AFTER)
        self.conn.execute(
            "UPDATE sources SET last_fetch_at=?, last_success_at=?, last_status='ok', last_error=NULL,"
            " consecutive_failures=0, failing_since=NULL, blocked=0, blocked_reason=NULL WHERE id=?", (now, now, src["id"]),
        )
        if was_failing:
            _record_change(self.conn, "adapter_recovered", "notice", source_id=src["id"], authority_id=src["authority_id"],
                           detail={"failed_since": src["failing_since"]})

    def _fail(self, src, error: str) -> None:
        now = utcnow()
        with tx(self.conn):
            failing_since = src["failing_since"] or src["last_success_at"] or now
            self.conn.execute(
                "UPDATE sources SET last_fetch_at=?, last_status='error', last_error=?, consecutive_failures=consecutive_failures+1,"
                " failing_since=? WHERE id=?",
                (now, error, failing_since, src["id"]),
            )
            over = datetime.fromisoformat(now) - datetime.fromisoformat(failing_since) > FAILING_AFTER
            already = self.conn.execute(
                "SELECT 1 FROM changes WHERE kind='adapter_failing' AND source_id=? AND detected_at >= ? LIMIT 1",
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
