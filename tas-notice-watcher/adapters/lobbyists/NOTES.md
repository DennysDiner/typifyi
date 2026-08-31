# Register of Lobbyists adapter notes

**Source:** Tasmanian Register of Lobbyists
**Status:** host and route confirmed as *existing*; **markup unverified** (see
`../DISCOVERY.md`).

## Correction to the brief

The brief expects a DPAC-hosted register. **The register moved to the Integrity
Commission on 1 July 2022**; DPAC administered it from 2009 until then. The live
register is `https://lobbyists.integrity.tas.gov.au/register`. The old DPAC host
(`lobbyists.dpac.tas.gov.au`) still resolves in search results with per-lobbyist
pages under `/lobbyists/<slug>`, so it is kept as a last-resort candidate — but
the Integrity Commission host is the one to trust.

## What is established

| Fact | Basis | Verified against the live page? |
| --- | --- | --- |
| Register at `lobbyists.integrity.tas.gov.au/register` | indexed page | no |
| Per-lobbyist pages at `/lobbyists/<slug>` (e.g. `…/lobbyists/font_public_relations`) | indexed pages on the DPAC host, same shape | no |
| The register holds business registration details, trading names, the individuals doing the lobbying, and the client list | register's own description | no |
| Lobbyists must list clients on retainer and clients represented in the previous three months | Code of Conduct summary | no |
| Administered by the Integrity Commission since 1 July 2022 | Integrity Commission / DPAC pages | no |

## How the adapter reads it

* Candidates: `/register`, then the Integrity Commission root, then the DPAC
  host.
* One item per lobbyist, id `lobbyists:<slug>`, taken from anchors matching
  `/lobbyists/<slug>`.
* **Detail pages are fetched every run**, not only when the index changes: a
  client list changes on the detail page while the index stays byte-identical.
  Conditional GET keeps that cheap, and a `304` re-uses the stored content hash
  rather than manufacturing a change.
* Fields pulled by label: trading name, ABN, address, owners/office holders,
  clients, employees. `published_at` is set only from a stated registration or
  update date; otherwise null and flagged.
* Removals **are** emitted — a lobbyist leaving the register is a
  deregistration, and that matters.

## Open questions (§9)

* **Does the register expose change history?** Every indication is that it shows
  current state only. If that holds, our gzipped archive is the only record of
  prior client lists, which raises its evidentiary value considerably — and makes
  the archive retention policy a decision worth taking deliberately rather than
  by default.
* Does the register state a "last updated" date per lobbyist? If it does, wire
  that label into `published_labels` and stop flagging these records.
* Is the client list rendered as a list, a table, or free text? This determines
  whether client-level diffing (rather than page-level) is worth adding — it
  probably is, since "client added" is the alert that matters.
* Are there sub-pages per lobbyist (e.g. historical registrations)?

## Failure expectations

* `min_expected_items = 3` — the register has consistently listed more than a
  handful of firms; three or fewer means the parse broke.
* Cadence expectation 12 h + 36 h grace.
