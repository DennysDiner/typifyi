"""Immutable, content-addressed archive.

Every fetched body is stored once under data/archive/<aa>/<bb>/<sha256>[.ext]. Nothing is ever
overwritten or deleted: a later fetch of the same URL with different bytes creates a new blob and a new
capture row; both remain. The `captures` table is the provenance ledger (URL, final URL, retrieval time,
HTTP status, response headers, sha256).
"""
from __future__ import annotations

import hashlib
import mimetypes
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
            self.conn.execute(
                "INSERT INTO blobs(sha256,size,content_type,path,first_seen_at) VALUES (?,?,?,?,?)",
                (sha, len(data), content_type, str(path.relative_to(self.root)), retrieved_at),
            )
        else:
            path = self.root / row[0]
        cur = self.conn.execute(
            "INSERT INTO captures(source_id,url,final_url,retrieved_at,http_status,headers,sha256,kind)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (source_id, url, final_url or url, retrieved_at, http_status, j(headers), sha, kind),
        )
        return Capture(id=int(cur.lastrowid), sha256=sha, path=path, new_blob=new_blob)

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
