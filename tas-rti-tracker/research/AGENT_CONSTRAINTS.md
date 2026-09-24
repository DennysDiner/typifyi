# Constraints for research agents (read first)

1. NETWORK: In this environment every *.tas.gov.au host, sttas.com.au, hydro.com.au, tasnetworks.com.au,
   utas.edu.au, austlii.edu.au, web.archive.org and most other sites are DENIED by the egress proxy.
   `curl` and `WebFetch` to them fail. Do not retry them. Do not try to route around the block.
   The ONLY working research channel is the `WebSearch` tool, which returns titles, URLs and short
   snippets. Run many narrow, specific searches (quote exact phrases, add "site:" hints in the query text).
2. EVIDENCE LABELS. Every fact and every URL you record carries one of:
   - `snippet_verified` : the fact/URL text appeared in a WebSearch result snippet or result URL.
   - `inferred`         : you reasoned it out (e.g. a URL pattern) but did not see it in a result.
   - `memory`           : from training knowledge only, not seen in any result this session.
   Never present `inferred` or `memory` as verified. Never invent a URL: a URL is recorded only if it
   appeared verbatim in a search result, otherwise leave the field null and say what you searched for.
3. Record the exact search queries you ran (a `queries:` list) so the work can be re-run when the
   network is opened, and so a later verifier can see what you did and did not check.
4. Where two sources disagree, or the snippet is ambiguous, write `UNCERTAIN` and explain. Do not
   pick an interpretation silently.
5. Output files must be valid YAML/Markdown, written with the Write tool to the exact paths given.
