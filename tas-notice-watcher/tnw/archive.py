"""Archive writers (§2.2).

Raw artefacts are stored gzipped and content-addressed by sha256 so that any
claim in an alert can be traced back to the exact bytes that were fetched.

The interface exists so that the migration from the repository to an
S3-compatible bucket is a single implementation swap: the content hash stays in
the path, so provenance survives the move.
"""

from __future__ import annotations

import gzip
import io
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .hashing import sha256_bytes
from .timeutil import parse_iso, utcnow_iso

# Extension by content type, so archived artefacts stay openable by hand.
_EXTENSIONS = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/plain": "txt",
    "application/json": "json",
    "application/rss+xml": "xml",
    "application/atom+xml": "xml",
    "text/xml": "xml",
    "application/xml": "xml",
}


def extension_for(content_type: str | None, url: str = "") -> str:
    if content_type:
        base = content_type.split(";", 1)[0].strip().lower()
        if base in _EXTENSIONS:
            return _EXTENSIONS[base]
    lowered = url.lower().split("?", 1)[0]
    for ext in ("pdf", "html", "htm", "xml", "json", "csv", "txt"):
        if lowered.endswith("." + ext):
            return "html" if ext == "htm" else ext
    return "bin"


@dataclass(frozen=True)
class ArchiveRef:
    """A pointer to an archived artefact."""

    path: str
    sha256: str
    size: int
    stored: bool  # False when the identical artefact was already archived


class ArchiveWriter(ABC):
    """Write-once, content-addressed artefact store."""

    @abstractmethod
    def write(
        self,
        source: str,
        data: bytes,
        *,
        content_type: str | None = None,
        url: str = "",
        fetched_at: str | None = None,
    ) -> ArchiveRef:
        ...

    @abstractmethod
    def read(self, path: str) -> bytes:
        """Return the original (un-gzipped) bytes for an archive path."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        ...

    @abstractmethod
    def describe(self) -> str:
        ...

    @staticmethod
    def _relative_path(source: str, digest: str, extension: str, fetched_at: str) -> str:
        moment = parse_iso(fetched_at)
        return f"{moment:%Y/%m}/{source}/{digest}.{extension}.gz"


class LocalGzipArchiveWriter(ArchiveWriter):
    """Stores gzipped artefacts under ``archive/YYYY/MM/<source>/<sha256>.<ext>.gz``."""

    def __init__(self, root: Path | str = "archive") -> None:
        self.root = Path(root)

    def write(
        self,
        source: str,
        data: bytes,
        *,
        content_type: str | None = None,
        url: str = "",
        fetched_at: str | None = None,
    ) -> ArchiveRef:
        digest = sha256_bytes(data)
        extension = extension_for(content_type, url)
        rel = self._relative_path(source, digest, extension, fetched_at or utcnow_iso())
        target = self.root / rel
        path = str(self.root / rel)
        if target.exists():
            return ArchiveRef(path=path, sha256=digest, size=len(data), stored=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        # mtime=0 keeps the gzip bytes deterministic, so identical content does
        # not produce a spurious git diff.
        with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
            handle.write(data)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(buffer.getvalue())
        os.replace(tmp, target)
        return ArchiveRef(path=path, sha256=digest, size=len(data), stored=True)

    def read(self, path: str) -> bytes:
        with gzip.open(path, "rb") as handle:
            return handle.read()

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def describe(self) -> str:
        return f"local-gzip:{self.root}"


class S3ArchiveWriter(ArchiveWriter):
    """S3-compatible archive (Cloudflare R2 and friends).

    Used once the repository approaches the size limit in §2.2. ``boto3`` is
    imported lazily so the dependency is only needed if this writer is selected.
    """

    def __init__(
        self,
        bucket: str,
        *,
        prefix: str = "archive",
        endpoint_url: str | None = None,
        client=None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if client is not None:
            self._client = client
        else:  # pragma: no cover - requires network credentials
            import boto3  # type: ignore[import-not-found]

            self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def _key(self, path: str) -> str:
        return path.split(f"{self.bucket}/", 1)[1] if path.startswith("s3://") else path

    def write(
        self,
        source: str,
        data: bytes,
        *,
        content_type: str | None = None,
        url: str = "",
        fetched_at: str | None = None,
    ) -> ArchiveRef:
        digest = sha256_bytes(data)
        extension = extension_for(content_type, url)
        rel = self._relative_path(source, digest, extension, fetched_at or utcnow_iso())
        key = f"{self.prefix}/{rel}" if self.prefix else rel
        path = f"s3://{self.bucket}/{key}"
        if self.exists(path):
            return ArchiveRef(path=path, sha256=digest, size=len(data), stored=False)
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
            handle.write(data)
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=buffer.getvalue(),
            ContentType="application/gzip",
            Metadata={"sha256": digest, "source": source, "fetched_at": fetched_at or ""},
        )
        return ArchiveRef(path=path, sha256=digest, size=len(data), stored=True)

    def read(self, path: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=self._key(path))
        return gzip.decompress(response["Body"].read())

    def exists(self, path: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(path))
        except Exception:
            return False
        return True

    def describe(self) -> str:
        return f"s3:{self.bucket}/{self.prefix}"
