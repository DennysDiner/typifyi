"""Archive writers: content addressing, gzip, dedup (§2.2, §1.3)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from tnw.archive import ArchiveRef, LocalGzipArchiveWriter, S3ArchiveWriter, extension_for
from tnw.hashing import sha256_bytes

FETCHED = "2026-08-31T21:05:00Z"


def test_artefact_is_gzipped_content_addressed_and_readable(tmp_path: Path):
    writer = LocalGzipArchiveWriter(tmp_path / "archive")
    data = b"%PDF-1.4 gazette bytes"
    ref = writer.write("gazette", data, content_type="application/pdf", fetched_at=FETCHED)

    assert ref.sha256 == sha256_bytes(data)
    assert ref.stored is True
    assert ref.path.endswith(f"2026/08/gazette/{ref.sha256}.pdf.gz")
    assert Path(ref.path).exists()
    assert gzip.decompress(Path(ref.path).read_bytes()) == data
    assert writer.read(ref.path) == data
    assert writer.exists(ref.path)


def test_identical_content_is_not_written_twice(tmp_path: Path):
    writer = LocalGzipArchiveWriter(tmp_path / "archive")
    first = writer.write("gazette", b"same", content_type="text/html", fetched_at=FETCHED)
    mtime = Path(first.path).stat().st_mtime_ns
    second = writer.write("gazette", b"same", content_type="text/html", fetched_at=FETCHED)
    assert second.stored is False
    assert second.path == first.path
    assert Path(first.path).stat().st_mtime_ns == mtime


def test_archive_bytes_are_deterministic(tmp_path: Path):
    a = LocalGzipArchiveWriter(tmp_path / "a")
    b = LocalGzipArchiveWriter(tmp_path / "b")
    ref_a = a.write("tenders", b"page", content_type="text/html", fetched_at=FETCHED)
    ref_b = b.write("tenders", b"page", content_type="text/html", fetched_at=FETCHED)
    assert Path(ref_a.path).read_bytes() == Path(ref_b.path).read_bytes()


@pytest.mark.parametrize(
    "content_type, url, expected",
    [
        ("application/pdf", "", "pdf"),
        ("text/html; charset=utf-8", "", "html"),
        (None, "https://x/y/a.PDF", "pdf"),
        (None, "https://x/y/a.htm?q=1", "html"),
        ("application/octet-stream", "https://x/y/z", "bin"),
    ],
)
def test_extension_selection(content_type, url, expected):
    assert extension_for(content_type, url) == expected


class FakeS3:
    """Enough of the S3 client surface to prove the interface swap works."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, **kwargs):  # noqa: N803 - boto3 casing
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        import io

        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        return {}


def test_s3_writer_keeps_the_content_hash_in_the_path():
    """Provenance must survive the migration out of the repository (§2.2)."""
    client = FakeS3()
    writer = S3ArchiveWriter("tnw-archive", client=client)
    ref = writer.write("gazette", b"bytes", content_type="application/pdf", fetched_at=FETCHED)
    assert isinstance(ref, ArchiveRef)
    assert ref.path == f"s3://tnw-archive/archive/2026/08/gazette/{ref.sha256}.pdf.gz"
    assert writer.read(ref.path) == b"bytes"
    assert writer.write("gazette", b"bytes", content_type="application/pdf",
                        fetched_at=FETCHED).stored is False
