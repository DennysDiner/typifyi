# tasmon — Tasmanian politics & government monitor

A personal media and document monitoring tool for a Tasmanian policy analyst.
Broad capture, rank-don't-filter: it ingests everything political it can reach,
scores each item (watchlist match × source tier × recency × political
salience), and produces a daily markdown digest plus immediate email alerts for
configured trigger rules.

No web framework, no docker, no cloud services required — Python 3.11+, SQLite,
and a handful of libraries. Everything you will ever want to edit (sources,
watchlist, aliases, weights, salience terms, alert rules) lives in
**`config.yaml`**.

## How it works

| Tier | What | How | Cadence |
|------|------|-----|---------|
| 1 | ABC Tas, Pulse, Tasmanian Times, Guardian Tas, Mirage News, government/party media releases, Parliament pages, agencies/regulators, GBEs | RSS where it exists; **page-diff monitoring** (hash the listing page, emit newly appearing links) where it doesn't; full text extracted with trafilatura | twice daily |
| 2 | The Mercury, The Examiner, The Advocate, AFR, The Australian (all paywalled) | Google News RSS scoped to each domain — headline, source, date, link only, flagged in the digest for manual reading. No paywall circumvention is built in, deliberately. | daily |
| 3 | ASIC published notices, EPBC referrals, FSC ANZ, international Trafigura coverage, Victorian forestry transition | page-diff / Google News | weekly |

- **Dedup**: items are keyed by a hash of the normalised URL (tracking params
  stripped); near-duplicates (wire copy republished across outlets) are
  suppressed by title similarity.
- **Watchlist** boosts ranking and can trigger immediate alerts — it never
  gates ingestion. Entity aliases ("STT" / "Sustainable Timber Tasmania" /
  "Forestry Tasmania") are part of each watchlist entry.
- **Digest** (`digests/YYYY-MM-DD.md` + terminal + optional email): watchlist
  hits, parliament/official publications, general news clustered by portfolio,
  paywalled headlines, and **source health** — a feed that has silently died
  is flagged every day until you fix or remove it. "Nothing new" is stated
  explicitly, never silently omitted.
- **Alerts**: config-driven trigger rules (e.g. Nyrstar + liquidat*/administrat*/
  receiver*) checked on every run; delivered by email the moment they match.

## Setup

```sh
cd tasmon
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# (if sgmllib3k fails to build on Debian/Ubuntu: pip install -U setuptools, retry)

python3 -m tasmon init          # creates data/tasmon.db
```

### Email (alerts + digest delivery)

Edit the `email:` block in `config.yaml`. The SMTP password is **not** stored
in config — it is read from the environment variable named by `password_env`
(default `TASMON_SMTP_PASS`). For Gmail, create an App Password
(Google Account → Security → 2-Step Verification → App passwords).

```sh
export TASMON_SMTP_PASS='your-app-password'
python3 -m tasmon test-email    # should land in your inbox
```

Set `digest.email: false` if you'd rather read the digest file on disk only,
and `alerts.channel: terminal` to keep alerts off email.

### First runs

```sh
python3 -m tasmon run --schedule tier1
python3 -m tasmon run --schedule tier2
python3 -m tasmon run --schedule tier3
python3 -m tasmon digest
```

Two things to know about the first day:

1. **Page-diff sources baseline silently on their first run** — they record
   the page's current links and only emit *newly appearing* links from then
   on. So the first digest will be mostly RSS/Google News items; page-diff
   sources start contributing from the second run.
2. **Check section 5 (source health) of the first digest.** Government sites
   restructure their URLs constantly; any source that failed is listed with
   its error. Fix the `url:`/`link_include:` in `config.yaml` and re-run.
   This is the tool's primary maintenance loop — a few minutes whenever a
   site moves.

## Scheduling

**Linux (cron)** — see `scripts/crontab.example`; edit paths and install with
`crontab scripts/crontab.example`. On **macOS** the same crontab works
(`crontab -e`), or use launchd if you prefer.

**Running it in the cloud**: any $5/month Linux VPS (or an always-on machine
at home) with cron is the recommended setup — with digest-by-email enabled the
whole thing is hands-off, and a laptop that's asleep at 6am misses the morning
sweep. Copy the directory, `pip install -r requirements.txt`, set
`TASMON_SMTP_PASS` in the crontab, done. The SQLite DB and digests live in
`data/` and `digests/` next to the config.

Default cadence (Hobart time): tier1 at 06:00 & 15:00, tier2 06:15, tier3
Monday 06:30, digest 06:45.

## Editing the watchlist

Everything is in `config.yaml`:

```yaml
watchlist:
  - entity: Nyrstar                       # canonical name shown in the digest
    aliases: ["Hobart smelter", Lutana]   # any alias match counts
    weight: 5                             # added to the score multiplier
```

Add/remove entries freely — they take effect on the next run, and matching is
case-insensitive on word boundaries with `*` wildcards (`liquidat*` matches
liquidation/liquidator/liquidate).

## Adding a source

```yaml
sources:
  - id: my-source            # unique, stable (used for dedup/health tracking)
    name: Human-readable name
    type: rss                # rss | google_news | page_diff
    url: https://.../feed    # rss & page_diff (google_news uses query:)
    tier: 1                  # 1 = full trust/full text, 2 = paywalled, 3 = periphery
    category: news           # news | government | parliament | agency | gbe | party
    fulltext: true           # tier 1 only: fetch article & extract text
    schedule: tier1          # tier1 (2x daily) | tier2 (daily) | tier3 (weekly)
```

For `page_diff` sources, `link_include:` is a list of substrings a link URL
must contain (and `link_exclude:` the reverse); links to other hosts are
ignored unless `same_host_only: false`. To trial a single source without
running the whole schedule: `python3 -m tasmon run --schedule tier1 --source my-source`.

## Alert rules

A rule fires when **every** group matches; each group is an any-of list:

```yaml
alerts:
  rules:
    - name: nyrstar-insolvency
      all_of:
        - [Nyrstar, "Hobart smelter", Trafigura]     # any of these, AND
        - [liquidat*, administrat*, receiver*]       # any of these
```

Each item can fire each rule at most once (tracked in the DB), so a story
republished across runs won't re-alert.

## Optional: Claude summarisation (v3)

Off by default. When enabled, high-ranking Tier 1 items with extracted full
text get a 2–3 sentence relevance note tuned to your briefing context,
appended under the item in the digest.

```sh
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

```yaml
summarization:
  enabled: true
  model: claude-haiku-4-5    # cheapest; switch to claude-opus-4-8 for best quality
  daily_cap: 15              # hard cap on API calls per day
```

At the default cap and model this costs on the order of a cent or two a day.

## Commands

```
python3 -m tasmon run --schedule tier1|tier2|tier3   # fetch, score, alert
python3 -m tasmon run --schedule tier1 --source ID   # test one source
python3 -m tasmon digest [--date YYYY-MM-DD] [--no-email]
python3 -m tasmon health                             # source health now
python3 -m tasmon test-email
python3 -m tasmon init
```

## Design notes

- Respects robots.txt for page and article fetches (declared RSS endpoints
  are fetched directly — that's what they're published for), sends an honest
  user-agent, throttles to one request per host per 1.5s, and backs off on
  errors.
- Ingestion never filters on topic; ranking and grouping happen at digest
  time. If the volume is wrong, tune `scoring:` weights, not the sources.
- Source URLs in the shipped config are best-effort as of July 2026 and were
  not all reachable from the build environment — treat the first digest's
  source-health section as the verification pass.
