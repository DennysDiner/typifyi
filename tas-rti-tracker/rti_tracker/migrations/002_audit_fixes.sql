-- 002: audit fixes — append-only provenance ledger with hash chain, removal confirmation, document rechecks,
-- per-application region, private attachments.

-- Provenance ledger: captures and blobs are append-only at the database level, not just by convention.
ALTER TABLE captures ADD COLUMN prev_chain_hash TEXT;
ALTER TABLE captures ADD COLUMN chain_hash TEXT;
CREATE TRIGGER captures_no_update BEFORE UPDATE ON captures BEGIN
  SELECT RAISE(ABORT, 'captures is append-only');
END;
CREATE TRIGGER captures_no_delete BEFORE DELETE ON captures BEGIN
  SELECT RAISE(ABORT, 'captures is append-only');
END;
CREATE TRIGGER blobs_no_update BEFORE UPDATE ON blobs BEGIN
  SELECT RAISE(ABORT, 'blobs is append-only');
END;
CREATE TRIGGER blobs_no_delete BEFORE DELETE ON blobs BEGIN
  SELECT RAISE(ABORT, 'blobs is append-only');
END;
CREATE TRIGGER listing_snapshots_no_delete BEFORE DELETE ON listing_snapshots BEGIN
  SELECT RAISE(ABORT, 'listing_snapshots is append-only');
END;

-- Removal confirmation and evidence.
ALTER TABLE items ADD COLUMN missing_polls INTEGER NOT NULL DEFAULT 0;   -- consecutive complete polls without the entry
ALTER TABLE items ADD COLUMN last_capture_id INTEGER REFERENCES captures(id);  -- last listing capture containing the entry
ALTER TABLE listing_snapshots ADD COLUMN complete INTEGER NOT NULL DEFAULT 1;   -- 0 if pagination was truncated
ALTER TABLE listing_snapshots ADD COLUMN capture_ids TEXT NOT NULL DEFAULT '[]'; -- all page captures

-- Sources: pinned detected format, document recheck bookkeeping, first failure time.
ALTER TABLE sources ADD COLUMN detected_format TEXT;
ALTER TABLE sources ADD COLUMN last_doc_recheck_at TEXT;
ALTER TABLE sources ADD COLUMN failing_since TEXT;

-- Applications: reference point for regional holidays; private attachments live outside the public archive.
ALTER TABLE applications ADD COLUMN region TEXT;
ALTER TABLE application_attachments ADD COLUMN path TEXT;
