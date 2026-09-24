from rti_tracker.archive import sha256_bytes


def test_store_is_content_addressed_and_immutable(archive, conn):
    c1 = archive.store(b"hello", url="https://x/a.pdf", content_type="application/pdf", headers={"etag": "1"}, http_status=200)
    c2 = archive.store(b"hello", url="https://x/b.pdf", content_type="application/pdf", headers={}, http_status=200)
    assert c1.sha256 == c2.sha256 == sha256_bytes(b"hello")
    assert c1.new_blob and not c2.new_blob
    assert c1.id != c2.id  # two captures, one blob
    assert conn.execute("SELECT count(*) FROM blobs").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM captures").fetchone()[0] == 2
    assert c1.path.read_bytes() == b"hello" and c1.path.suffix == ".pdf"
    # different bytes for the same URL -> new blob, old one kept
    c3 = archive.store(b"hello2", url="https://x/a.pdf", content_type="application/pdf", headers={}, http_status=200)
    assert c3.sha256 != c1.sha256 and c1.path.exists() and c3.path.exists()
    assert archive.verify(c1.sha256) and archive.verify(c3.sha256)


def test_verify_detects_tampering(archive):
    c = archive.store(b"data", url="https://x/t.txt", content_type="text/plain", headers={}, http_status=200)
    c.path.write_bytes(b"tampered")
    assert not archive.verify(c.sha256)
