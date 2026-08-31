# Gazette adapter notes

**Source:** Tasmanian Government Gazette
**Status:** endpoints identified from search-index metadata; **markup unverified**
(see `../DISCOVERY.md`).

## What is established

| Fact | Basis | Verified against the live page? |
| --- | --- | --- |
| Host is `www.gazette.tas.gov.au` | search results, current | no |
| Per-year index pages at `/editions/<year>` | indexed pages for `/editions/2023`, `/editions/2024` | no |
| Issue PDFs live under `/editions/<year>/<month>-<year>/<number>_-_Gazette_<d Month yyyy>.pdf` | indexed PDF, e.g. `/editions/2026/january-2026/22542_-_Gazette_14_January_2026.pdf` | no |
| Published weekly, Wednesdays at 16:00; special and periodical gazettes appear ad hoc | site's own "About"/"Where to get the Gazette" text | no |
| Online archive runs from 2008; printed indexes issued twice yearly (January, July) | same | no |
| Issue numbers are sequential five-digit integers (22542 → 14 Jan 2026, 22599 → 12 Aug 2026) | two indexed PDFs, consistent with weekly cadence | no |

## How the adapter reads it

* Fetches `/editions/<current year>` (plus the previous year during January, when
  the current-year index is nearly empty), falling back to the site root.
* Takes every anchor whose resolved href matches `/editions/….pdf`.
* Issue number: the first 4–6 digit run in the link text or filename → item id
  `gazette:<number>`. No number found → id is derived from the URL hash and the
  item is flagged `issue_number_not_found_in_link`.
* Publication date: parsed from the date stated in the link text or filename
  ("14 January 2026"). If no date is stated, `published_at` stays **null** and
  the record is flagged. The fetch date is never substituted.
* Special/periodical issues are labelled in `source_notes` (`kind: special`).
* PDFs are downloaded (budget: `TNW_MAX_DOCUMENTS`, default 6 per run), archived
  gzipped, and read with `pdfplumber`. Issues already seen with an unchanged
  listing entry are never re-downloaded: a published gazette is immutable.
* Items whose PDF has not been fetched yet carry `body_pending`; they alert as
  new immediately and as changed once the text arrives, with the reason stated
  in the alert.

## Open questions (§9)

* **Are the PDFs text-layer or image-only?** Unresolved: no PDF has been opened.
  The adapter reports `no_text_layer` in `source_notes` and as a run warning when
  a fetched issue yields under 200 characters. If that fires routinely, OCR is
  required and M0 roughly doubles in effort — that is a decision for a human, and
  the adapter will not guess at content it cannot read.
* Does an index page or feed exist beyond the per-year listing (an RSS/Atom link,
  a JSON endpoint, a sitemap)? `discover` reports whether the page advertises a
  feed; check before adding more scraping.
* Are special gazettes listed on the same year index, or somewhere separate? If
  separate, add that URL to `candidate_urls`.
* Page count per issue: `TNW_MAX_PDF_PAGES` (default 400) bounds extraction. A
  truncated read is reported as a warning, never silently.

## Failure expectations

* `min_expected_items = 1` — a year index with no PDF links at all is a parse
  failure.
* Fetch cadence expectation: 12 h + 24 h grace. A weekly gazette that has been
  silent for ten days shows as `stale` in the heartbeat, which is the intended
  behaviour: broken parser until proven otherwise.
