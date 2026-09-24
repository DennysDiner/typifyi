"""Immutable, content-addressed archive.

Every fetched body is stored once under data/archive/<aa>/<bb>/<sha256>[.ext]. Nothing is ever
overwritten or deleted: a later fetch of the same URL with different bytes creates a new blob and a new
capture row; both remain. The `captures` table is the provenance ledger (URL, final URL, retrieval time,
HTTP status, response headers, sha256).
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import j, utcnow

_EXT_BY_TYPE = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "application/json": ".json",
    "text/csv": ".csv",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tif",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chain_hash(prev: str, url: str, final_url: str, retrieved_at: str, sha: str, kind: str) -> str:
    return hashlib.sha256("|".join([prev, url, final_url or "", retrieved_at, sha, kind]).encode()).hexdigest()


def guess_ext(content_type: str | None, url: str = "") -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXT_BY_TYPE:
        return _EXT_BY_TYPE[ct]
    if url:
        tail = url.split("?")[0].rsplit("/", 1)[-1]
        if "." in tail and len(tail.rsplit(".", 1)[1]) <= 5:
            return "." + tail.rsplit(".", 1)[1].lower()
    return mimetypes.guess_extension(ct) or ".bin"


@dataclass
class Capture:
    id: int
    sha256: str
    path: Path
    new_blob: bool


class Archive:
    def __init__(self, conn: sqlite3.Connection, root: Path):
        self.conn = conn
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def blob_path(self, sha: str, ext: str = ".bin") -> Path:
        return self.root / sha[:2] / sha[2:4] / f"{sha}{ext}"

    def store(
        self,
        data: bytes,
        *,
        url: str,
        content_type: str | None,
        headers: dict[str, str],
        http_status: int | None,
        final_url: str | None = None,
        source_id: int | None = None,
        kind: str = "document",
        retrieved_at: str | None = None,
    ) -> Capture:
        """Store bytes (idempotent on content) and record a capture. Always creates a capture row."""
        sha = sha256_bytes(data)
        retrieved_at = retrieved_at or utcnow()
        row = self.conn.execute("SELECT path FROM blobs WHERE sha256=?", (sha,)).fetchone()
        new_blob = row is None
        if new_blob:
            ext = guess_ext(content_type, url)
            path = self.blob_path(sha, ext)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                tmp = path.with_suffix(path.suffix + ".part")
                tmp.write_bytes(data)
                tmp.replace(path)
                os.chmod(path, 0o444)  # blobs are read-only on disk
            self.conn.execute(
                "INSERT INTO blobs(sha256,size,content_type,path,first_seen_at) VALUES (?,?,?,?,?)",
                (sha, len(data), content_type, str(path.relative_to(self.root)), retrieved_at),
            )
        else:
            path = self.root / row[0]
        # Hash chain: each capture commits to every capture before it, so a later edit or deletion of any
        # row breaks verification (see `verify_chain`). Rows are also protected by append-only triggers.
        prev = self.conn.execute("SELECT chain_hash FROM captures ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = prev[0] if prev and prev[0] else "0" * 64
        chain = chain_hash(prev_hash, url, final_url or url, retrieved_at, sha, kind)
        cur = self.conn.execute(
            "INSERT INTO captures(source_id,url,final_url,retrieved_at,http_status,headers,sha256,kind,prev_chain_hash,chain_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (source_id, url, final_url or url, retrieved_at, http_status, j(headers), sha, kind, prev_hash, chain),
        )
        return Capture(id=int(cur.lastrowid), sha256=sha, path=path, new_blob=new_blob)

    def store_private(self, data: bytes, filename: str) -> tuple[str, Path]:
        """Store a private file (Kurt's attachments) under archive/private/, with NO capture or blob row, so
        it never appears in the public ledger or Datasette. Returns (sha256, path)."""
        sha = sha256_bytes(data)
        path = self.root / "private" / sha[:2] / f"{sha}_{filename}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
            os.chmod(path, 0o400)
        return sha, path

    def verify_chain(self) -> tuple[int, list[int]]:
        """Recompute the capture hash chain; return (rows checked, ids of rows that break the chain)."""
        prev = "0" * 64
        bad: list[int] = []
        n = 0
        for r in self.conn.execute("SELECT id,url,final_url,retrieved_at,sha256,kind,prev_chain_hash,chain_hash FROM captures ORDER BY id"):
            n += 1
            if r["chain_hash"] is None:  # rows written before migration 002 are unchained
                continue
            expect = chain_hash(prev, r["url"], r["final_url"], r["retrieved_at"], r["sha256"], r["kind"])
            if r["prev_chain_hash"] != prev or r["chain_hash"] != expect:
                bad.append(int(r["id"]))
            prev = r["chain_hash"]
        return n, bad

    def chain_head(self) -> str | None:
        """Current head of the hash chain — publish/anchor this (e.g. OpenTimestamps, a dated tweet, a
        commit) to make the ledger tamper-evident against the database owner too."""
        r = self.conn.execute("SELECT chain_hash FROM captures WHERE chain_hash IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        return r[0] if r else None

    def open_path(self, sha: str) -> Path:
        row = self.conn.execute("SELECT path FROM blobs WHERE sha256=?", (sha,)).fetchone()
        if not row:
            raise FileNotFoundError(sha)
        return self.root / row[0]

    def read(self, sha: str) -> bytes:
        return self.open_path(sha).read_bytes()

    def verify(self, sha: str) -> bool:
        """Re-hash the on-disk blob and confirm it still matches its name."""
        try:
            return sha256_bytes(self.read(sha)) == sha
        except FileNotFoundError:
            return False
