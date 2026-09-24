# Decisions

Every judgment call made while building the tracker, with the reason. Newest at the bottom.

## D1. Standalone store, merge-ready entity table
Neither the media-monitoring tool nor `tas-notice-watcher` was present in this repository or in the
repositories available to the session (`DennysDiner/typifyi`, `DennysDiner/typitest` only). The tracker
therefore has its own SQLite store, but `entities(id, kind, name, aliases, external_ids)` is the shared
identity table: authority ids are stable slugs (`stt`, `hydro`, `launceston_cc`, `min_abetz`) meant to be
reused by the other tools, and `external_ids` is a JSON map reserved for their identifiers. Merging later is
an `INSERT … ON CONFLICT` of that table plus a rename of any clashing slugs.

## D2. Location in the repository
The project lives in `tas-rti-tracker/` at the repository root rather than mixed into the typing-practice
files, so it can be split into its own repository (or merged with the notice watcher) without history surgery.

## D3. Network policy blocked every primary source — everything is labelled by evidence
The session's egress policy denied every `*.tas.gov.au` host, AustLII, archive.org, council, GBE and UTAS
domains (HTTP 403 CONNECT from the proxy; documented in `research/AGENT_CONSTRAINTS.md`). `WebSearch` was the
only channel and it is capped at 200 calls per session; the cap was exhausted part-way through the registry
research. Consequences:
- `LEGAL_MODEL.md` and `legal/rules.yaml` were built from search-result text, not the Act. Every rule carries
  `evidence: snippet_verified|inferred|memory`, `uncertain` and `pinpoint_uncertain`. The brief said "don't
  hardcode any timeframe from memory": the code contains no numbers at all; the rules file does, and every
  memory-only number is marked so (`external_review_deemed_refusal_window: days: null`, `working_day: memory`).
- No disclosure log page was ever fetched, so `disclosure_log_format` is `unknown` for all but two
  authorities and adapter tests use synthetic fixtures (`tests/fixtures/README.md`). `rti fixtures record`
  exists to capture real pages once the network is open, and `tests/test_recorded_fixtures.py` replays them.
- The annual RTI report PDF could not be fetched, so the registry-vs-report cross-check is implemented
  (`rti annual import`, `rti annual crosscheck`) but has not been run. This is the largest open item in
  the definition of done.
Kurt's environment settings must allow (at least) `*.tas.gov.au`, `*.tas.gov.au` council domains,
`hobartcity.com.au`, `launceston.tas.gov.au`, `burnie.net`, `sttas.com.au`, `hydro.com.au`,
`tasnetworks.com.au`, `tasports.com.au`, `tasrail.com.au`, `tt-line.com.au`, `tasirrigation.com.au`,
`maib.tas.gov.au`, `utas.edu.au`, `taswater.com.au`, `austlii.edu.au` before the verification pass can run.

## D4. Working-day arithmetic and regional holidays
`legal/rules.yaml` marks the s 5 "working day" definition and the regional-holiday question UNCERTAIN.
Rather than pick a reading, `DeadlineEngine` computes each date under both readings (statewide-only and
statewide + the authority's region) and shows a range when they differ. Day counting starts the day after
the trigger event ("not later than N working days after …"); the due date is the Nth working day.

## D5. Holiday calendar is sourced, not typed
Statewide holidays come from the `holidays` PyPI package (AU/TAS, which cites the Statutory Holidays Act
2000); the package version is recorded with each row. That package does not carry Tasmania's regional days.
`legal/holidays/regional.yaml` holds memory-derived regional entries marked `verified: false`; the engine
ignores unverified entries unless `--include-unverified-regional` is passed. `rti holidays import-csv`
loads an official list (WorkSafe Tasmania) and marks entries verified with the source URL.

## D6. Alerts channel
The brief said to ask whether Kurt wants ntfy or email. That could not be asked mid-build, so both are
implemented and each activates only when its environment variables are set (`config/alerts.yaml`,
`.env.example`). Default channel list includes `stdout` so a dry run always shows what would be sent.

## D7. Registry merge and dedupe rules
`scripts/merge_registry.py` merges the three research slices deterministically. Duplicates: `tascorp` and
`public_trustee` take the GBE slice record (Treasury lists them as GBEs); `utas` and `taswater` take the
local-government slice record. Slice ids were normalised to snake_case (`publictrustee → public_trustee`,
`tasirrigation → tas_irrigation`, `marinuslink → marinus_link`). Ministers all share DPAC's single
ministerial log, so a synthetic owner record `ministers_dpac_log` holds the polled source and each minister
record carries `shares_source_with: ministers_dpac_log`. Corrections go in `registry/overrides.yaml`; the
slice files are the research record and are not edited by hand.

## D8. `state_growth` stays active
State Growth became Building Tasmania on 2026-07-02 (slice research, snippet-verified). Its legacy log URL
is still polled under `state_growth` (Tier 1) because historical releases live there and no Building
Tasmania log URL was found. Once one is found, add it to `building_tas` and set `state_growth` to
`active: false` in overrides; history stays attributable through `authority_names` / `authority_urls`.

## D9. Unknown formats use the `auto` adapter
Every authority with a disclosure-log URL but `disclosure_log_format: unknown` gets a source with the
`auto` adapter, which tries `html_table`, `html_list` and `per_release_pages` (or `pdf_index` for a PDF
body) and records the winner in the source config. `rti registry suggest-formats` prints the detections so
the registry can be updated after review. This replaces the brief's plan for parallel bespoke-adapter
worktrees: with no site reachable, bespoke adapters would have been written blind against imagined layouts.
A `rti_tracker/adapters/bespoke/` package is auto-loaded if present for site-specific adapters later.

## D10. An empty parse is an error, not a mass removal
If a listing that previously had items parses to zero, the monitor records a failure and refuses to mark
anything removed (`allow_empty: true` in the source config overrides). Layout changes are far more common
than a log being emptied, and a false "everything was removed" alert would be worse than a delayed one.

## D11. Fingerprints are listing-level
Item fingerprints cover the listing entry (title, link, date, listed fields, linked document URLs as
listed), not the contents of a per-release page. A release page that later gains a document is caught on
`rti poll --force` or when the listing entry changes. This keeps re-polls cheap and avoids re-fetching every
release page on every tick.

## D12. Hosting
Cron and systemd timers are the primary options (`deploy/`); a GitHub Actions workflow is provided but
carries caveats (best-effort cron, state must be persisted, runner IPs). The web UI binds to localhost and
gates on HTTP basic auth when `RTI_WEB_USER` is set. Datasette hides the application tables. Nothing is
deployed publicly; that decision is Kurt's (brief §4).

## D13. Stack
Datasette over the same SQLite file for faceted exploration plus a small FastAPI + Jinja2 + htmx app for the
opinionated views (feed, authority pages, applications, changes, campaigns). No JS build step; htmx is
loaded from a CDN in the template and can be vendored into `web/static/` for an offline deployment.

## D14. Hansard is stubbed
The Parliament search endpoint could not be observed; the adapter returns nothing until
`search_url_template` is configured and it is disabled in `config/scheduler.yaml` (brief §2 allowed this).

## D15. Python 3.12
The container default is 3.11 but 3.12 is installed; the venv uses 3.12 per the brief. No 3.12-only syntax
is used, so 3.11 would also work.

## D16. Legal-model spot-checks by the orchestrator
Checked against my own reading of the Act where the agent's evidence was thin: s 15(1) 20 working days and
the +20 for third-party consultation match; s 43 internal-review application window of 20 working days
matches; the internal-review decision period (15 vs 20) genuinely conflicts across sources and the rules
file shows both; the deemed-refusal subsection and the s 44/s 45 split are plausibly right but unverified.
None of these checks is a substitute for reading the consolidated Act; see the verification checklist at
the end of `LEGAL_MODEL.md`.

## D17. Removals need two consecutive complete polls
The audit showed pagination and transient glitches would generate false "silent removal" claims, which are the
single most damaging false positive this tool could produce. A removal is now recorded only after an entry is
missing from two consecutive complete crawls (also evaluated on unchanged/304 polls), and the record carries the
last capture that contained the entry and the first that did not. Cost: a real removal is alerted one poll later
(about an hour for Tier 1). `removal_confirm_polls` in a source's config changes this.

## D18. D11 corrected: document rechecks
D11 claimed `--force` would catch a replaced PDF. It did not. `Monitor.recheck_documents()` re-fetches current
documents with conditional GETs (`rti recheck-docs`, and three sources per `rti run` tick, oldest first).

## D19. Provenance ledger is append-only and chained
Captures and blobs cannot be updated or deleted at the database level (triggers); each capture commits to the
previous one via a hash chain; blob files are read-only. `rti archive verify` checks both and prints the chain
head. The head must be anchored somewhere outside the machine (OpenTimestamps, a dated post) for the ledger to
be tamper-evident against the database owner. That step needs network access and is on Kurt.

## D20. Coverage statistics: only "searched, none found" is a finding
The coverage report now distinguishes authorities where a log-specific search was run from those never searched,
and excludes business units. Until every row has a recorded search and the annual-report cross-check has run,
none of these counts should be quoted externally.

## D21. Precautionary deadlines are shown for the applicant's own windows only
Where the Act's time limit could not be established (Ombudsman application after a deemed refusal),
`legal/rules.yaml` may declare `precautionary_days`; the engine then shows a clearly labelled PRECAUTIONARY,
UNCERTAIN date and alerts on it. Precautionary dates are never used to assert that an authority is late: a
deemed refusal is asserted only once the later of the two working-day readings has passed.
