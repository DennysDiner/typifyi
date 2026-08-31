# Discovery status — read this before trusting any adapter

§3 of the brief requires a discovery pass that confirms the current endpoint,
format and update pattern for each source before any selector is hardcoded.

**That pass is only half done, and the half that is missing is the half that
needs a network.** The environment this code was written in blocks outbound
connections to every `*.tas.gov.au` host (the egress proxy rejects the CONNECT
with a 403), so no page from any of the four sources has been fetched, and no
markup from any of them has been read. What is recorded in each adapter's
`NOTES.md` comes from search-engine metadata: live URLs, page titles, snippets
and the site's own descriptions of itself. That is enough to establish which
hosts and routes exist. It is not enough to verify a selector.

Two things follow, and both are built into the code rather than left as
warnings:

1. **Extraction keys on routes and labels, not on markup.** Adapters find items
   by the shape of the links a page contains (`/editions/…​.pdf`,
   `/tender/view/…`, `/lobbyists/<slug>`) and pull fields by their visible
   labels ("Closing Date", "Agency"). Government sites re-theme far more often
   than they re-route, and a class-based selector fails silently the day a theme
   changes.
2. **A wrong guess alerts instead of returning nothing.** Every adapter declares
   a minimum item count; a 200 response that yields fewer raises
   `AdapterParseError`, which becomes a `FAILURE` issue. Each adapter also
   carries several candidate listing URLs and records the one that worked in
   `state/<source>.json`, so a site restructure shows up as a state diff rather
   than a quiet switch.

## Finish the discovery pass on the first live run

From the repository (Actions has unrestricted egress):

```
gh workflow run tas-notice-watcher.yml -f mode=discover      # or the mobile app
```

or locally / in a Codespace:

```
python -m tnw discover
```

`discover` fetches each candidate URL, reports status, content type, size, ETag,
link counts and a sample of matched links, and writes
`adapters/<source>/DISCOVERY.json`. Then, for each source:

* update `NOTES.md` with what was actually observed, and mark the "verified"
  column;
* capture a real page as a fixture — `python -m tnw capture-fixture --url … --out
  tests/fixtures/<source>/<name>.html` — and replace the synthetic fixture the
  parser tests currently use (`tests/fixtures/README.md` explains which are
  which);
* adjust `min_expected_items` to a number the real listing comfortably exceeds.

Until that is done, treat every alert as provisional and check the archived
artefact before quoting anything from it.
