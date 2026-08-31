# tas-notice-watcher

Change detection for Tasmanian government publication surfaces — the Gazette,
tenders, contract disclosures and the Register of Lobbyists — with
entity-matched alerts and an evidence-grade archive behind every claim.

Runs entirely on GitHub Actions. There is no server, no database and no local
machine in the loop: the repository *is* the database, GitHub Issues *is* the
interface, and everything can be driven from a phone.

---

## What it does, once per half-day

```
fetch → archive raw → normalise → extract items → hash → diff vs state
      → match watchlist → alert → commit state
```

* **Fetch** — conditional GET (`ETag`/`Last-Modified`), `robots.txt` respected,
  a `User-Agent` carrying a contact address, ≥2 s between requests to a host,
  exponential backoff on 5xx, and a 4xx treated as a structural failure that
  alerts.
* **Archive** — every artefact stored gzipped and content-addressed by sha256 at
  `archive/YYYY/MM/<source>/<sha256>.<ext>.gz`. Every alert line can be traced
  back to the exact bytes fetched.
* **Extract** — each adapter returns a list of `Item` records, never a blob.
* **Diff** — keyed by item id, so reordering a listing changes nothing. Emits
  `new`, `changed` and `removed`; a withdrawn tender or a deregistered lobbyist
  is a story.
* **Match** — the watchlist, case-insensitively and word-boundary anchored, over
  title and full body text. Near misses go to a review list rather than the bin.
* **Alert** — one GitHub issue per run with changes; separate `FAILURE` issues
  when something breaks. Recurring failures comment on their existing issue
  instead of opening a new one every run.

Nothing in an alert is machine-summarised, and no language model produces any
value, date, name or amount that enters a record. Parsing is deterministic (§1.4
of the brief).

## Getting an answer out of it from a phone

* **Alerts arrive as GitHub issues**, push-notified by the GitHub mobile app,
  labelled by source, with tier-1 watchlist hits promoted into the title. Close
  an issue as you work it — it doubles as the triage queue.
* **Run it now**: Actions → *tas-notice-watcher* → *Run workflow*. Choose
  `run`, `discover`, `check` or `digest`, optionally narrow to one source, and
  optionally tick *dry run*.
* **Read the evidence**: the archive path in each alert is a path in this
  repository.

## First thing to do: finish the discovery pass

The endpoints below were identified from search-index metadata, **not** by
fetching the pages — the environment this was built in cannot reach
`*.tas.gov.au`. Read [`adapters/DISCOVERY.md`](adapters/DISCOVERY.md) before
trusting any adapter, then run `discover` from Actions and update each
`adapters/<source>/NOTES.md`.

| Source | Surface the adapter targets | Notes |
| --- | --- | --- |
| Gazette | `gazette.tas.gov.au/editions/<year>` → issue PDFs | weekly (Wed 16:00) plus specials; PDF text layer unconfirmed |
| Tenders | `tenders.tas.gov.au/tender/list` (candidates tried in order) | removals meaningful |
| Contracts | `tenders.tas.gov.au/ContractAwarded/List/DateAwarded` | award date ≠ publication date |
| Lobbyists | `lobbyists.integrity.tas.gov.au/register` | **moved from DPAC on 1 July 2022**; current state only |

## Layout

```
adapters/            one package per source, each with NOTES.md and its own expectations
  base.py            the adapter interface and shared fetch/archive/item helpers
  listing.py         configurable HTML listing adapter (tenders, contracts, lobbyists)
  htmlutil.py        route- and label-based extraction helpers
tnw/                 the engine: fetch, normalise, hash, diff, match, alert, report
state/               per-source JSON: item index, hashes, ETags, run history, heartbeat
archive/YYYY/MM/     gzipped raw artefacts, content-addressed by sha256
records/             append-only NDJSON, one file per source per month
records/review/      near-miss log for human review
outputs/             Atom feed and NDJSON export (M4)
watchlist.yml        entity patterns and priority tiers
tests/fixtures/      saved HTML/PDF; the test suite makes no network calls
docs/OPERATIONS.md   runbook: triage, tuning, archive migration, fixtures
```

## The Item schema

Every adapter emits exactly these fields, and anything failing validation is
rejected and alerted rather than written as a partial row:

| field | notes |
| --- | --- |
| `id` | source-native identifier, else a sha256 of the canonical fields |
| `source` | `gazette` \| `tenders` \| `contracts` \| `lobbyists` |
| `title` | |
| `published_at` | ISO 8601, **source-stated**; `null` if the source states none — never the fetch date |
| `url` | |
| `body_text` | extracted text; may be truncated *in the record* (the archive holds the full text) |
| `entities` | matched watchlist entities |
| `content_hash` | sha256 over the canonical fields, computed after normalisation |
| `fetched_at` | ISO 8601 UTC |
| `http_status` | |
| `archive_path` | path to the gzipped raw artefact |
| `source_notes` | parser caveats as `token` / `token: detail`, e.g. `no_text_layer`, `body_pending` |

Per-source structured fields (agency, supplier, closing date, contract value…)
ride at the head of `body_text` as a deterministic `key: value` block, so the
schema stays fixed while the extra fields stay greppable.

## Failure detection

Silent failure is the project's main risk, so absence of alerts is made
distinguishable from absence of events:

* **Heartbeat** — a source that has not fetched successfully within its interval
  plus grace opens a `FAILURE` issue, even if it was not selected for that run.
* **Canary counts** — each adapter declares a minimum item count; too few items
  from a 200 response is a parse failure, not a quiet week.
* **Schema validation** — invalid records are rejected and alerted.
* **Structural drift** — a sharp move in items-per-byte against the trailing
  median is logged as a warning before it becomes a breakage.
* **Run summary** — every run writes `state/heartbeat.json` and an Actions job
  summary with per-source status, counts, requests, bytes and duration.

## Commands

```
python -m tnw run [--sources gazette,tenders] [--force] [--dry-run] [--no-alert]
python -m tnw discover [--sources …]     # probe endpoints, write DISCOVERY.json
python -m tnw check                      # heartbeat only
python -m tnw digest --days 7            # weekly digest issue
python -m tnw feed                       # outputs/feed.xml (Atom)
python -m tnw export --since 2026-08-01T00:00:00Z
python -m tnw validate                   # watchlist, records and state
python -m tnw match --text "…"           # try the watchlist against some text
python -m tnw capture-fixture --url … --out tests/fixtures/…
```

Configuration is by environment variable: `TNW_CONTACT` (put a real contact
address in the `TNW_CONTACT` repository variable), `TNW_MIN_INTERVAL_S`,
`TNW_MAX_DOCUMENTS`, `TNW_MAX_DETAIL_PAGES`, `TNW_MAX_PDF_PAGES`,
`TNW_MAX_BODY_CHARS`, `TNW_ARCHIVE_BACKEND` (`local` | `s3`) and the
`TNW_ARCHIVE_S3_*` settings.

## Development

```
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
python -m pytest -q
```

Dependencies are pinned with hashes (`uv pip compile --generate-hashes`).
The test suite is offline by construction; see `tests/fixtures/README.md` for
what each fixture is and where it came from.

## Status against the milestones

| Milestone | Code | Acceptance |
| --- | --- | --- |
| **M0** scaffold + one source end to end | done | offline: a run archives, records and commits state. **A green *scheduled* run against the live Gazette has not happened** (no network here). |
| **M1** diff and alerting | done | offline: a new issue produces exactly one alert with matched entities and working archive paths; a re-run with no change produces none. |
| **M2** failure detection | done | offline: breaking a selector in a fixture produces a `FAILURE` alert instead of an empty result (`tests/test_runner.py::test_m2_…`). |
| **M3** remaining adapters | done | all four adapters exist behind one interface with fixture tests and their own `NOTES.md`. The "under 10 minutes for all four" criterion needs a live run to measure; per-run budgets are set to keep it there. |
| **M4** outputs | done | weekly digest issue, Atom feed (parsed and validated in tests), NDJSON export. |

**What is genuinely unfinished:** every acceptance criterion that requires
touching the live sites. The adapters are written against documented routes, not
observed markup, and will need one discovery pass plus fixture capture before
their output should be quoted in anything. That is the first task after this
lands — see `adapters/DISCOVERY.md`.

## Non-goals

No authenticated or paywalled surfaces. No public republication of source
documents (keep this repository private; confirm licensing before redistributing
anything — Tasmanian government material is frequently but not universally
CC BY). No LLM-generated factual extraction. No web UI. No characterisation of
what a notice *means*: the tool surfaces and matches, analysis stays human.
