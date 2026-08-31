# Operations runbook

Everything here can be done from a phone unless it says otherwise.

## Daily: triaging an alert

1. The issue title names the change count, any tier-1 entities and the sources.
2. Each item lists its stated publication date, URL, matched entities and
   archive path. **Check the archive path before quoting anything.** The archived
   file is the evidence; the record is a convenience.
3. `stated publication date: **not stated by source**` means exactly that. Do
   not substitute the fetch date, and do not let it become "published on" in a
   briefing.
4. Close the issue when the items are worked. It is the triage queue.

## When a FAILURE issue appears

| Kind | What it means | First move |
| --- | --- | --- |
| `parse` | The page was fetched but yielded no items | Open the archived HTML for that run; compare against the adapter's `NOTES.md`. Capture a new fixture, fix the extractor, then fix the test. |
| `canary` | Fewer items than the adapter's declared minimum | Same as `parse`. If the source genuinely shrank, lower `min_expected_items` **and write down why**. |
| `fetch` | 4xx (structural) or repeated 5xx | 4xx usually means the route moved: run `discover` and update the candidate list. |
| `robots` | robots.txt now disallows the path, or could not be read | Do not work around it. Check whether the disallow is real; if it is, that source stops until there is another lawful surface. |
| `schema` | A record failed validation | The record was rejected, not written. Read the errors in the issue body; they name the field. |
| `stale` | No successful fetch inside interval + grace | The parser is broken until proven otherwise. Run the workflow manually with `--sources <name>` and read the summary. |

A recurring failure comments on its existing issue rather than opening a new one,
so an issue that keeps growing is one problem, not many.

## Running things by hand

Actions → *tas-notice-watcher* → *Run workflow*:

* `run` — the full pipeline (a manual dispatch always runs, regardless of slot).
* `discover` — probe every candidate endpoint and write
  `adapters/<source>/DISCOVERY.json`. Do this before changing any selector.
* `check` — heartbeat only; useful to confirm the watcher is alive.
* `digest` — the weekly digest issue on demand.

## Tuning

Repository variable `TNW_CONTACT` should hold a real contact address; it goes
into the `User-Agent` of every request. Other settings are environment variables
(see the README table). The ones that matter in practice:

* `TNW_MAX_DOCUMENTS` — gazette PDFs downloaded per run (default 6). Raise it to
  backfill; lower it if runs get long.
* `TNW_MAX_DETAIL_PAGES` — detail pages per listing source per run (default 25).
* `TNW_MAX_PDF_PAGES` — pages read from one PDF (default 400). A truncated read
  is reported as a warning, never silently.
* `TNW_MIN_INTERVAL_S` — politeness delay per host (default 2 s). Do not lower.

## Adding a watchlist entity

Edit `watchlist.yml` on GitHub (the pencil icon works fine on a phone), commit,
and CI validates it. Tiers: 1 campaign-critical (promoted into issue titles),
2 tracked, 3 background. Prefer several precise literals over one loose regex.

Read `records/review/near-misses.ndjson` occasionally: it is where renamed
entities and special-purpose vehicles show up first.

## Capturing a fixture after a parser bug

Every production parser bug gets a fixture **before** the fix:

```
python -m tnw capture-fixture \
  --url https://www.tenders.tas.gov.au/tender/list \
  --out tests/fixtures/tenders/tender-list.html
```

This also writes a `.meta.json` recording URL, status, content type and fetch
time. Add it to the table in `tests/fixtures/README.md` with its real
provenance, write the failing test, then fix the parser.

## Moving the archive out of the repository

The archive writer is behind an interface precisely so this is one swap. When
`archive/` approaches ~400 MB (the watch workflow warns), create a Cloudflare R2
(or any S3-compatible) bucket and set:

```
TNW_ARCHIVE_BACKEND=s3
TNW_ARCHIVE_S3_BUCKET=<bucket>
TNW_ARCHIVE_S3_ENDPOINT=<https://…r2.cloudflarestorage.com>
AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY as repository secrets
```

and add `boto3` to `requirements.in`, then recompile the lockfile. New artefacts
get `archive_path` values of the form
`s3://<bucket>/archive/YYYY/MM/<source>/<sha256>.<ext>.gz` — the content hash
stays in the path, so provenance survives the move. Keep the existing
`archive/` directory in the repository (or move it to the bucket with the same
key layout); do not rewrite historical `archive_path` values in records.

## Things that must not drift

* `published_at` is never back-filled from the fetch date.
* No LLM produces a value, date, name or amount that enters a record.
* A test is never made to pass by lowering a canary count without a written
  reason.
* Nothing from `archive/` is republished without checking the licence on the
  source material.
