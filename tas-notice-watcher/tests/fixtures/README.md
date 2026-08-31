# Fixtures

The test suite has **no network access** (§7). Everything a parser test needs is
in this directory.

## Provenance — read this before trusting a parser test

| Fixture | Provenance |
| --- | --- |
| `gazette/editions-2026.html` | **Synthetic.** Modelled on the documented URL shape (`/editions/<year>/<month>-<year>/<number>_-_Gazette_<d Month yyyy>.pdf`) and the site's stated weekly cadence. |
| `gazette/editions-2026-broken.html` | **Synthetic.** The same page after a hypothetical redesign that removes the anchors — the negative case for §5's "zero items is a failure". |
| `gazette/sample-gazette.pdf` | **Synthetic**, built by `build_pdfs.py`. Real text layer. |
| `gazette/scanned-gazette.pdf` | **Synthetic**, built by `build_pdfs.py`. No text operators: stands in for an image-only issue. |
| `tenders/*.html`, `contracts/*.html` | **Synthetic.** Modelled on the documented `/Tender/View/<id>` and `/ContractAwarded/View/<id>` routes and on the field labels those listings are described as carrying. |
| `lobbyists/*.html` | **Synthetic.** Modelled on the documented `/lobbyists/<slug>` route. `detail-font-changed.html` is the same page with one client added — the change that matters most on this source. |
| `normalise/page-fetch-{a,b}.html` | **Synthetic.** Two "fetches" of one page differing *only* in volatile content (CSRF token, nonce, cache-buster, ad slot, render timestamp, visitor counter, viewstate, session id in a link). |
| `normalise/page-fetch-c-real-change.html` | **Synthetic.** Identical to fetch A except one closing date — the negative control, which must hash differently. |

**No fixture here was captured from a live Tasmanian government page**, because
the environment this was built in cannot reach those hosts (see
`../../adapters/DISCOVERY.md`). They encode the *documented* shape of each
source, so they test the parser's logic honestly, but they cannot prove the
parser matches the real markup. Replace them with captured pages on the first
live run:

```
python -m tnw capture-fixture --url https://www.gazette.tas.gov.au/editions/2026 \
    --out tests/fixtures/gazette/editions-2026.html
```

That writes the page plus a `.meta.json` recording the URL, status, content type
and fetch time, so a fixture's provenance stays checkable.

## Rule for production bugs (§7)

Every production parser bug gets a fixture captured from the failing page
**before** the fix is written, added to the table above with its real
provenance.

## Rebuilding the PDFs

```
python tests/fixtures/build_pdfs.py
```
