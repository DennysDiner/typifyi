# Research to re-run when the network is open

The session's WebSearch budget (200 calls) ran out during the registry research and no target site was
fetchable. The following lists are the queued work, in priority order.

1. Read the Act and Regulations at legislation.tas.gov.au (current consolidation) against the
   "Verification checklist" in LEGAL_MODEL.md; update legal/rules.yaml.
2. Fetch the RTI annual reports (all years) from the Department of Justice page and run
   `rti annual import` + `rti annual crosscheck`.
3. Per-council "disclosure log" searches: see `queries_not_run` on each council record in
   registry/slices/local_gov_other.yaml (0 of 29 councils have a verified log URL).
4. GBE/SOC RTI pages never searched: STT, Metro, Tascorp, PAHSMA, TasWater, Marinus Link, Public Trustee
   (registry/slices/gbe_soc.yaml header lists the queries).
5. State bodies: `meta.failed_queries` in registry/slices/state_bodies.yaml, plus a Building Tasmania
   disclosure log URL, and the current DPAC / ministerial log URLs (old-site paths).
6. WorkSafe Tasmania statutory holidays list → `rti holidays import-csv`.
7. Audit follow-ups needing the network (research/AUDIT_RESPONSE.md): Tier 1 log URLs for justice,
   building_tas, stt, tasnetworks, tasports, tasrail, ttline, tas_irrigation, maib, launceston_cc (audit #1,
   #62: STT and TasTAFE are reported by the ABC as publishing; Justice notes a "Disclosure Register"); verify
   the 2026 machinery-of-government facts (#11); resolve UNCERTAIN statuses against ss 5–6 (#6); former
   Ministers for historical attribution (#5); Easter Tuesday and the s 45 time limit (#15, #20); external
   anchoring of the archive chain head (#38).
