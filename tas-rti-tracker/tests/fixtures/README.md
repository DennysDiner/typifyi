# Fixtures

`synthetic/` — hand-built pages modelled on common Tasmanian disclosure-log layouts. They are NOT
recordings of live sites: the build environment's network policy blocked every *.tas.gov.au host, so
no live page could be captured. Each adapter is exercised against these.

`recorded/` — (empty until the network is opened) live captures made with
`rti fixtures record <authority>` which stores the listing body + headers under the authority id so the
adapter test can replay it. Re-record whenever a site changes layout.
