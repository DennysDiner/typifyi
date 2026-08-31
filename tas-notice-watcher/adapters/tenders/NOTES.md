# Tenders adapter notes

**Source:** Tasmanian Government Tenders (open opportunities)
**Status:** host and route family identified; **listing route and markup
unverified** (see `../DISCOVERY.md`).

## What is established

| Fact | Basis | Verified against the live page? |
| --- | --- | --- |
| Host is `www.tenders.tas.gov.au`, reachable from `www.purchasing.tas.gov.au` | Treasury purchasing pages | no |
| Routes are ASP.NET-style `/<Area>/<Action>[/<sort>]` | indexed pages `/ContractAwarded/List/DateAwarded`, `/PurchaseOrder/List`, `/registration` | no |
| Browsing and searching are public; registration only adds email alerts | site's own description | no |
| Agencies must report contracts ≥ $50,000 on this site | Treasury/purchasing guidance | no |
| The home page states a rolling count of tenders published in the last 7 days | indexed snippet | no |
| No RSS/Atom feed found | absence in search results — **weak evidence, re-check** | no |

## How the adapter reads it

Candidate listings, tried in order (the one that works is recorded in
`state/tenders.json`):

1. `/tender/list`
2. `/Tender/List`
3. `/tender/search`
4. `/` (home page, last resort)

Rows are found by anchors matching `/tender/(view|details|display)/…`; the row
is the anchor's nearest container, and fields are pulled by visible label:
tender id, agency, category, closing date, status. `published_at` is only set
from an explicit "Published"/"Advertised"/"Release date" label — a closing date
is never promoted into it. Detail pages are fetched for new or changed rows
(budget `TNW_MAX_DETAIL_PAGES`, default 25) and their text is stored beneath a
deterministic `key: value` block.

Pagination: up to 3 listing pages are followed via `rel="next"` or a "Next"
link. If the real listing paginates differently, raise `max_list_pages` or add
the paged URL as a candidate.

Removals **are** emitted: the current-tenders view is a complete picture of what
is open, so a tender disappearing from it is a withdrawal and is a story.

## Open questions (§9)

* Is there an RSS/Atom feed or JSON endpoint? Check `discover` output before
  extending the HTML scraper — a feed would remove most of this code.
* Does the open-tenders listing paginate, and does it use query parameters
  (`?page=2`) or POST-backed paging? POST-backed paging would need a different
  approach; note it here if so.
* Is a tender's detail URL stable across its lifetime (open → closed → awarded)?
  If the id changes at award, link tenders to contracts by tender number rather
  than URL.
* Confirm whether the site sets `ETag`/`Last-Modified` (conditional GET is
  already used; without validators every run re-downloads the listing).

## Failure expectations

* `min_expected_items = 1`; raise this once the true steady-state count is known
  (the home page's "3 new tenders in the last 7 days" suggests the open list is
  comfortably in the dozens — a listing that suddenly yields 1 should alert).
