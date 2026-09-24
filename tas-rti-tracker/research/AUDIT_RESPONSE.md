# Response to the independent audit (research/AUDIT_REPORT.md)

Status per finding. **Fixed** = code/config changed and covered by a test where practical. **Deferred (network)** =
cannot be done in the build environment (every Tasmanian government host is blocked, search budget exhausted);
listed in research/RERUN.md. **Design** = a judgement call, recorded in DECISIONS.md.

| # | Sev | Status | What changed |
|---|---|---|---|
| 1 | blocker | Partly fixed / deferred (network) | `rti health` now reports `TIER1_NO_SOURCE` as a failure state and exits 1. The 10 missing Tier 1 log URLs (Justice, Building Tas, STT, TasNetworks, TasPorts, TasRail, TT-Line, Tas Irrigation, MAIB, Launceston) need the network to find. Do not describe Tier 1 as monitored until `rti health` exits 0. |
| 2 | blocker | Fixed | coverage_report.md now separates *searched, none found* (21, provisional) from *not yet searched* (98, not a finding), excludes business units, and carries a warning header. The "144" figure is withdrawn. |
| 3 | high | Fixed | 34 business units re-typed `business_unit` / `rti_status: via_parent` via registry/overrides.yaml; excluded from coverage and health. `crown_law` included. |
| 4 | high | Deferred (network) | `rti annual import` + `rti annual crosscheck` exist; PDFs not fetchable here. |
| 5 | medium | Fixed (as UNCERTAIN) | Law Society (partial, s 6), Marine Farming Planning Review Panel, Launceston Flood Authority, Rivers and Water Supply Commission, Poppy Advisory and Control Board, Veterinary Board, Racing Appeals Board, Forest Practices Tribunal added with basis "auditor memory". Former Ministers: deferred. |
| 6 | medium | Deferred (needs the Act) | Statuses left UNCERTAIN; noted in RERUN.md. |
| 7 | medium | Fixed | Inactive authorities get no source; leftover sources disabled on sync; health lists `ORPHAN_SOURCE_INACTIVE_AUTHORITY`. Test added. |
| 8 | medium | Fixed | `tlgc` shares Treasury's source. Test added. |
| 9 | medium | Fixed | Shared sources with `attribution: authority_names` attribute each entry to the Minister named in it (ministers_dpac_log configured). Former ministers stay active for attribution. |
| 10 | medium | Fixed | `rti app new --region` / `applications.region` sets the reference point per application. |
| 11 | medium | Deferred (network) | 2026 MoG facts remain snippet-only; flagged in the registry notes. |
| 12 | low | Fixed | `resolve_authority` is exact-match only; `candidates=True` returns fuzzy suggestions for a human. Test added. |
| 13 | low | Design | Tier promotion happens once a log exists (config/scheduler.yaml). |
| 14 | low | Fixed | Sources whose URL left the registry are disabled on sync. |
| 15 | high | Fixed | `precautionary_days: 20` on `external_review_deemed_refusal_window` (evidence: auditor memory, UNCERTAIN); engine shows a PRECAUTIONARY window and alerts on it. Test added. |
| 16 | high | Fixed | Missing `decision_maker` → both windows shown + warning + next step to record it. `minister_delegate` value added (UNCERTAIN). Test added. |
| 17 | medium | Fixed | Extensions/consultation decisions dated after the base period expired are not applied (`late_extension_policy`, UNCERTAIN) and a warning is shown. Test added. |
| 18 | medium | Fixed | 30-wd alternative only appears when a `negotiation_commenced` event exists (`requires_event`). Test added. |
| 19 | medium | Fixed | `Deadline.display()` prints the alternative reading. |
| 20 | medium | Deferred (needs the Act) | Easter Tuesday noted in rules.yaml working_day notes; no data source to model it honestly. |
| 21 | medium | Fixed (structure) | regional.yaml keyed by municipality with a municipality→region map; Recreation Day listed for north and north-west; Devonport Cup added. Still unverified and ignored by default. |
| 22 | medium | Fixed | Warning now says regional holidays are NOT applied when no verified calendar is loaded; `--include-unverified-regional` flag added to `rti app status`; deemed refusal asserted only once the LATER reading has passed; Kurt's precautionary window anchored to that date. Test added. |
| 24 | low | Fixed | State-label sections come from `rules.yaml: state_sections` (s 22 flagged memory/UNCERTAIN). |
| 25–27 | low | Fixed (wording) | rules.yaml publication/annual-reporting notes softened and reconciled. |
| 28 | low | Fixed | `[MET]` / `[MISSED]` / `[PASSED]` / `[open]` status words. |
| 29 | low | Fixed | `decision_notified.detail.received_date` starts the s 43 clock when present. Test added. |
| 30 | low | Fixed | `minister_delegate` decision-maker value, flagged UNCERTAIN, shows both windows. |
| 31 | blocker | Fixed | Heuristic pagination (rel=next, pager classes, "Next/›/»"); a truncated crawl never counts removals; a removal needs 2 consecutive complete polls (also evaluated on unchanged/304 polls); removal records carry before/after capture ids. Tests added. |
| 32 | blocker | Fixed | Reference regex requires a prefix or FY-style token and rejects date shapes; stable keys include the title. Test added. |
| 33 | high | Fixed | Any status other than 200/304 is `FetchError`; zero items on any poll is an error. Tests added. |
| 34 | high | Fixed | `Monitor.recheck_documents()` (conditional GET + re-hash) via `rti recheck-docs`, and up to 3 sources per `rti run` tick; cron example includes a daily recheck. Test added. DECISIONS D11 corrected. |
| 35 | high | Fixed | ETag/Last-Modified stored only after a successful parse. Test added. |
| 36 | high | Fixed | Detected format persisted to `sources.detected_format` and pinned; a switch records `adapter_format_switched` and suppresses removals that poll. |
| 37 | high | Fixed | `last_seen_at`/`last_capture_id` refreshed on every successful poll including 304; removal detail records last-capture-with and first-capture-without. Shown on the item page. |
| 38 | high | Fixed (local) / Deferred (external anchor) | Append-only triggers on captures/blobs/listing_snapshots; hash chain over captures; blobs chmod 0444; `rti archive verify` checks the chain and prints the head to anchor externally. External timestamping needs network. |
| 39 | medium | Fixed | Removal coinciding with a similar-titled new entry is labelled `possible_replacement` at notice severity. |
| 40 | medium | Fixed | Reverts reinstate the earlier document row (`document_reverted`); each source's poll is exception-isolated so one failure cannot abort the tick. Test added. |
| 41 | medium | Fixed | `document_unavailable` (404/410) recorded on fetch and recheck, with archived hashes. Test added. |
| 42 | medium | Fixed | Manual imports recorded as `kind='manual_import'` with a `file://` URL and the claimed source in headers. |
| 43 | medium | Fixed | robots.txt 5xx/unreachable ⇒ disallow (RFC 9309); robots re-checked for a redirect target host; `Retry-After` honoured. Test added. |
| 44 | medium | Partly fixed | `flock` in cron and systemd examples. Per-host state stays in-process (design: one process at a time). |
| 45 | medium | Fixed | `failing_since` column; a never-succeeded source raises `adapter_failing` after 24 h. Test added. |
| 46 | low | Fixed | Polling refuses to start without `RTI_CONTACT_EMAIL`. |
| 47, 48, 50 | low | Partly | Furniture links ("application form", "policy"…) excluded from html_list heuristics; pdf_index link pairing unchanged (documented). Page captures beyond page 1 are stored in `listing_snapshots.capture_ids`. |
| 49 | low | Fixed | Adjacent sources appear in health; Ombudsman URL switched to the snippet-verified `reasons-for-decisions` path. |
| 51 | low | Fixed | Deadline alerts fire when due-or-overdue and unsent; `holidays` pinned to 0.105. |
| 52 | low | Partly | Deadline tests now include independently stated expected dates for the audit's scenarios via the hand-worked table; monitor edge cases added. |
| 53 | high | Fixed | GitHub Actions example no longer writes data/ into git; state goes to private storage via rclone with a warning header. |
| 54 | high | Fixed | Datasette: `allow: false` on applications, events, attachments, links, deadline_alerts_sent, alerts, kv; `allow_sql: false`. |
| 55 | high | Fixed | FTS snippets HTML-escaped then re-marked; `/archive/{sha}` served as `application/octet-stream` attachment with `Content-Security-Policy: sandbox` and `nosniff`; CSP on app pages; htmx pinned with SRI. |
| 56 | medium | Fixed | Auth fails closed (user without password ⇒ 503); same-origin check on POSTs; `TrustedHostMiddleware`. |
| 57 | medium | Fixed | Attachments stored under `archive/private/` with no captures/blobs rows; served via `/private/{app}/{sha}`. |
| 58 | medium | Fixed | Item page shows listing captures, final URL, ledger chain prefix and removal before/after evidence. |
| 59 | low | Documented | `.env.example` says to use a private ntfy topic + token. |
| 60 | low | Fixed | `canon_url` drops non-http(s) schemes. |
| 61 | high | Partly | Doc-link recognition extended (getmedia, DocumentCenter, download.aspx, Drive/OneDrive, `sites/default/files`). Spreadsheet/Word/JS-rendered logs remain unsupported (documented in README "adapter limits"). |
| 62 | medium | Deferred (network) | Candidate log URLs listed in RERUN.md. |
| 63 | medium | Partly | Cabinet decisions and Right to Know added as disabled adjacent sources with UNVERIFIED URLs. |
| 64 | low | Documented | Bot challenges surface as `blocked`; README says to treat as a coverage gap. |
