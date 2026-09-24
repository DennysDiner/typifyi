-- 001_init: core schema. All timestamps are ISO-8601 UTC strings.

CREATE TABLE schema_migrations (
  version     TEXT PRIMARY KEY,
  applied_at  TEXT NOT NULL
);

-- Shared entity table. Designed to merge with tas-notice-watcher / media monitor:
-- id is a stable slug shared across tools; kind distinguishes authorities, people, companies.
CREATE TABLE entities (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('authority','person','company','minister','other')),
  name         TEXT NOT NULL,
  aliases      TEXT NOT NULL DEFAULT '[]',   -- JSON array
  external_ids TEXT NOT NULL DEFAULT '{}',   -- JSON object: {abn:..., notice_watcher_id:..., media_id:...}
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE authorities (
  id                    TEXT PRIMARY KEY REFERENCES entities(id),
  name                  TEXT NOT NULL,
  type                  TEXT NOT NULL,
  rti_status            TEXT NOT NULL,
  rti_status_basis      TEXT,
  portfolio_minister    TEXT,
  parent_id             TEXT REFERENCES authorities(id),
  region                TEXT,
  rti_page_url          TEXT,
  disclosure_log_url    TEXT,
  disclosure_log_format TEXT NOT NULL DEFAULT 'unknown',
  rti_contact_email     TEXT,
  annual_report_url     TEXT,
  website               TEXT,
  tier                  INTEGER NOT NULL DEFAULT 2,
  active                INTEGER NOT NULL DEFAULT 1,
  verification_status   TEXT,
  last_verified         TEXT,
  source_of_listing     TEXT NOT NULL DEFAULT '[]',  -- JSON array
  notes                 TEXT,
  raw                   TEXT NOT NULL DEFAULT '{}'   -- full registry record as JSON
);

-- Historical names/URLs so old releases remain attributable after MoG changes.
CREATE TABLE authority_names (
  id             INTEGER PRIMARY KEY,
  authority_id   TEXT NOT NULL REFERENCES authorities(id),
  name           TEXT NOT NULL,
  effective_from TEXT,
  effective_to   TEXT,
  source         TEXT
);
CREATE INDEX idx_authority_names_name ON authority_names(name);

CREATE TABLE authority_urls (
  id             INTEGER PRIMARY KEY,
  authority_id   TEXT NOT NULL REFERENCES authorities(id),
  url            TEXT NOT NULL,
  kind           TEXT NOT NULL,   -- website|rti_page|disclosure_log|annual_report
  effective_from TEXT,
  effective_to   TEXT,
  source         TEXT
);

CREATE TABLE minister_portfolios (
  id             INTEGER PRIMARY KEY,
  portfolio      TEXT NOT NULL,
  minister       TEXT NOT NULL,
  department_ids TEXT NOT NULL DEFAULT '[]',
  effective_from TEXT,
  effective_to   TEXT,
  evidence       TEXT,
  campaign_relevant INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE mog_changes (
  id        INTEGER PRIMARY KEY,
  date      TEXT NOT NULL,
  change    TEXT NOT NULL,
  from_ids  TEXT NOT NULL DEFAULT '[]',
  to_ids    TEXT NOT NULL DEFAULT '[]',
  evidence  TEXT
);

-- A source is one polled URL (a disclosure log, an Ombudsman decisions page, ...).
CREATE TABLE sources (
  id                   INTEGER PRIMARY KEY,
  authority_id         TEXT REFERENCES authorities(id),
  kind                 TEXT NOT NULL DEFAULT 'disclosure_log', -- disclosure_log|ombudsman_decisions|annual_report|hansard
  adapter              TEXT NOT NULL,
  url                  TEXT NOT NULL,
  tier                 INTEGER NOT NULL DEFAULT 2,
  enabled              INTEGER NOT NULL DEFAULT 1,
  config               TEXT NOT NULL DEFAULT '{}',
  etag                 TEXT,
  last_modified        TEXT,
  listing_hash         TEXT,
  last_fetch_at        TEXT,
  last_success_at      TEXT,
  last_change_at       TEXT,
  last_status          TEXT,
  last_error           TEXT,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  blocked              INTEGER NOT NULL DEFAULT 0,
  blocked_reason       TEXT,
  robots_checked_at    TEXT,
  robots_allowed       INTEGER,
  next_due_at          TEXT,
  UNIQUE(authority_id, kind, url)
);

-- Immutable content-addressed blobs.
CREATE TABLE blobs (
  sha256        TEXT PRIMARY KEY,
  size          INTEGER NOT NULL,
  content_type  TEXT,
  path          TEXT NOT NULL,
  first_seen_at TEXT NOT NULL
);

-- Every successful retrieval: URL + time + headers + hash. Never updated, never deleted.
CREATE TABLE captures (
  id           INTEGER PRIMARY KEY,
  source_id    INTEGER REFERENCES sources(id),
  url          TEXT NOT NULL,
  final_url    TEXT,
  retrieved_at TEXT NOT NULL,
  http_status  INTEGER,
  headers      TEXT NOT NULL DEFAULT '{}',
  sha256       TEXT NOT NULL REFERENCES blobs(sha256),
  kind         TEXT NOT NULL DEFAULT 'document'  -- listing|document|robots|other
);
CREATE INDEX idx_captures_url ON captures(url);
CREATE INDEX idx_captures_sha ON captures(sha256);

-- Every fetch attempt including failures and 304s (for health / politeness auditing).
CREATE TABLE fetches (
  id           INTEGER PRIMARY KEY,
  source_id    INTEGER REFERENCES sources(id),
  url          TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status_code  INTEGER,
  not_modified INTEGER NOT NULL DEFAULT 0,
  bytes        INTEGER,
  error        TEXT,
  capture_id   INTEGER REFERENCES captures(id)
);

CREATE TABLE listing_snapshots (
  id           INTEGER PRIMARY KEY,
  source_id    INTEGER NOT NULL REFERENCES sources(id),
  retrieved_at TEXT NOT NULL,
  listing_hash TEXT NOT NULL,     -- sha256 of the normalised parsed listing
  item_count   INTEGER NOT NULL,
  capture_id   INTEGER REFERENCES captures(id)
);

-- An item is one entry in a disclosure log (one release). external_key is the adapter's stable key.
CREATE TABLE items (
  id                  INTEGER PRIMARY KEY,
  source_id           INTEGER NOT NULL REFERENCES sources(id),
  authority_id        TEXT REFERENCES authorities(id),
  external_key        TEXT NOT NULL,
  title               TEXT,
  url                 TEXT,
  reference           TEXT,
  published_date      TEXT,
  decision_date       TEXT,
  fields              TEXT NOT NULL DEFAULT '{}',   -- current parsed fields JSON
  fingerprint         TEXT NOT NULL,
  first_seen_at       TEXT NOT NULL,
  last_seen_at        TEXT NOT NULL,
  removed_at          TEXT,
  status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','removed')),
  UNIQUE(source_id, external_key)
);
CREATE INDEX idx_items_authority ON items(authority_id, first_seen_at);

CREATE TABLE item_versions (
  id          INTEGER PRIMARY KEY,
  item_id     INTEGER NOT NULL REFERENCES items(id),
  seen_at     TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  fields      TEXT NOT NULL,
  snapshot_id INTEGER REFERENCES listing_snapshots(id)
);

CREATE TABLE documents (
  id                 INTEGER PRIMARY KEY,
  item_id            INTEGER REFERENCES items(id),
  authority_id       TEXT REFERENCES authorities(id),
  url                TEXT NOT NULL,
  sha256             TEXT NOT NULL REFERENCES blobs(sha256),
  capture_id         INTEGER NOT NULL REFERENCES captures(id),
  content_type       TEXT,
  filename           TEXT,
  first_seen_at      TEXT NOT NULL,
  superseded_by      INTEGER REFERENCES documents(id),  -- set when the same URL later yields new bytes
  text_extracted_at  TEXT,
  extraction_method  TEXT,
  ocr_applied        INTEGER NOT NULL DEFAULT 0,
  page_count         INTEGER,
  text_chars         INTEGER,
  UNIQUE(url, sha256)
);
CREATE INDEX idx_documents_item ON documents(item_id);

CREATE TABLE document_text (
  document_id INTEGER PRIMARY KEY REFERENCES documents(id),
  text        TEXT NOT NULL
);

CREATE VIRTUAL TABLE document_fts USING fts5(
  text, content='document_text', content_rowid='document_id', tokenize='porter unicode61'
);
CREATE TRIGGER document_text_ai AFTER INSERT ON document_text BEGIN
  INSERT INTO document_fts(rowid, text) VALUES (new.document_id, new.text);
END;
CREATE TRIGGER document_text_ad AFTER DELETE ON document_text BEGIN
  INSERT INTO document_fts(document_fts, rowid, text) VALUES ('delete', old.document_id, old.text);
END;
CREATE TRIGGER document_text_au AFTER UPDATE ON document_text BEGIN
  INSERT INTO document_fts(document_fts, rowid, text) VALUES ('delete', old.document_id, old.text);
  INSERT INTO document_fts(rowid, text) VALUES (new.document_id, new.text);
END;

-- LLM-extracted metadata, one row per field, each with its own verification status.
CREATE TABLE document_metadata (
  id                INTEGER PRIMARY KEY,
  document_id       INTEGER NOT NULL REFERENCES documents(id),
  field             TEXT NOT NULL,
  value             TEXT,
  evidence_quote    TEXT,
  verified          INTEGER NOT NULL DEFAULT 0,   -- 1 = value supported by document text
  verification_note TEXT,
  model             TEXT,
  extracted_at      TEXT NOT NULL,
  UNIQUE(document_id, field)
);

CREATE TABLE changes (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,   -- new_item|item_edited|item_removed|item_reappeared|new_document|document_changed|adapter_failing|adapter_recovered|source_blocked|deadline|deemed_refusal
  severity    TEXT NOT NULL DEFAULT 'info',  -- info|notice|high
  source_id   INTEGER REFERENCES sources(id),
  authority_id TEXT REFERENCES authorities(id),
  item_id     INTEGER REFERENCES items(id),
  document_id INTEGER REFERENCES documents(id),
  detected_at TEXT NOT NULL,
  detail      TEXT NOT NULL DEFAULT '{}',
  alerted_at  TEXT,
  digested_at TEXT
);
CREATE INDEX idx_changes_detected ON changes(detected_at);

CREATE TABLE alerts (
  id        INTEGER PRIMARY KEY,
  change_id INTEGER REFERENCES changes(id),
  channel   TEXT NOT NULL,
  rule      TEXT NOT NULL,
  payload   TEXT NOT NULL,
  sent_at   TEXT,
  status    TEXT NOT NULL DEFAULT 'pending',
  error     TEXT
);

CREATE TABLE campaigns (
  id        TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  keywords  TEXT NOT NULL DEFAULT '[]',
  notes     TEXT
);

CREATE TABLE campaign_tags (
  id          INTEGER PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  document_id INTEGER REFERENCES documents(id),
  item_id     INTEGER REFERENCES items(id),
  tagged_at   TEXT NOT NULL,
  tagged_by   TEXT NOT NULL DEFAULT 'kurt',  -- kurt|watchlist
  note        TEXT
);

-- Kurt's own applications. Never public.
CREATE TABLE applications (
  id             INTEGER PRIMARY KEY,
  authority_id   TEXT REFERENCES authorities(id),
  authority_name TEXT,
  lodged_date    TEXT NOT NULL,
  accepted_date  TEXT,
  scope          TEXT NOT NULL,
  reference      TEXT,
  fee_amount     REAL,
  fee_waiver     TEXT,
  status         TEXT NOT NULL DEFAULT 'lodged',
  notes          TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);

CREATE TABLE application_events (
  id             INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications(id),
  event          TEXT NOT NULL,   -- from legal rules: application_lodged, application_accepted, third_party_consultation_notified, extension_agreed, transfer, decision_notified, internal_review_lodged, ...
  event_date     TEXT NOT NULL,
  section        TEXT,
  detail         TEXT NOT NULL DEFAULT '{}',
  recorded_at    TEXT NOT NULL
);

CREATE TABLE application_attachments (
  id             INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications(id),
  filename       TEXT NOT NULL,
  sha256         TEXT NOT NULL REFERENCES blobs(sha256),
  description    TEXT,
  added_at       TEXT NOT NULL
);

CREATE TABLE application_links (
  id             INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications(id),
  item_id        INTEGER REFERENCES items(id),
  matched_by     TEXT NOT NULL,   -- reference|scope_similarity|manual
  confidence     REAL NOT NULL,
  linked_at      TEXT NOT NULL,
  confirmed      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE deadline_alerts_sent (
  id             INTEGER PRIMARY KEY,
  application_id INTEGER NOT NULL REFERENCES applications(id),
  deadline_id    TEXT NOT NULL,
  due_date       TEXT NOT NULL,
  days_before    INTEGER NOT NULL,
  sent_at        TEXT NOT NULL,
  UNIQUE(application_id, deadline_id, due_date, days_before)
);

CREATE TABLE ombudsman_decisions (
  id           INTEGER PRIMARY KEY,
  reference    TEXT,
  authority_id TEXT REFERENCES authorities(id),
  authority_raw TEXT,
  decision_date TEXT,
  title        TEXT,
  url          TEXT NOT NULL,
  document_id  INTEGER REFERENCES documents(id),
  outcome      TEXT,
  summary      TEXT,
  first_seen_at TEXT NOT NULL,
  UNIQUE(url)
);

CREATE TABLE annual_stats (
  id             INTEGER PRIMARY KEY,
  report_year    TEXT NOT NULL,      -- e.g. 2024-25
  authority_id   TEXT REFERENCES authorities(id),
  authority_raw  TEXT NOT NULL,
  metric         TEXT NOT NULL,
  value          REAL,
  source_url     TEXT,
  sha256         TEXT,
  page           INTEGER,
  extracted_at   TEXT NOT NULL,
  UNIQUE(report_year, authority_raw, metric)
);

CREATE TABLE hansard_mentions (
  id           INTEGER PRIMARY KEY,
  date         TEXT,
  chamber      TEXT,
  speaker      TEXT,
  authority_id TEXT REFERENCES authorities(id),
  url          TEXT NOT NULL,
  excerpt      TEXT,
  first_seen_at TEXT NOT NULL,
  UNIQUE(url, excerpt)
);

CREATE TABLE holidays (
  id           INTEGER PRIMARY KEY,
  date         TEXT NOT NULL,
  name         TEXT NOT NULL,
  region       TEXT NOT NULL DEFAULT 'statewide',   -- statewide|north|south|north_west|<specific>
  source       TEXT NOT NULL,       -- library:holidays==x.y | url
  retrieved_at TEXT NOT NULL,
  UNIQUE(date, name, region)
);

CREATE TABLE kv (
  key   TEXT PRIMARY KEY,
  value TEXT
);
