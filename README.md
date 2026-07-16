# Chief of Staff Tracker

A self-updating job board for Chief of Staff roles at startups. A GitHub Action polls
public ATS job boards (Greenhouse, Lever, Ashby) every 6 hours, keeps a persistent
history in `data/jobs.json`, and rebuilds a static dashboard served by GitHub Pages.

## Setup (one time, ~10 minutes)

1. **Create a new GitHub repo** (public or private both work) and push these files to it.
2. **Enable GitHub Pages**: repo → Settings → Pages → Source: "Deploy from a branch"
   → Branch: `main`, folder: `/docs` → Save. Your dashboard will live at
   `https://<your-username>.github.io/<repo-name>/`.
   (On a private repo, Pages requires a paid GitHub plan — a public repo is free.)
3. **Allow the Action to push**: repo → Settings → Actions → General →
   Workflow permissions → select "Read and write permissions" → Save.
4. **Run it once manually**: repo → Actions → "Scrape CoS listings" → Run workflow.
   When it finishes (and Pages deploys, ~1 min), your dashboard URL shows the first
   batch of listings.

That's it. It now runs itself every 6 hours.

## LLM screening (optional, recommended)

If you add an Anthropic API key, every new listing's full description gets screened by
Claude (Haiku — fast and cheap) and badged on the dashboard:

- **STRONG FIT** — genuinely strategic Chief of Staff work
- **BORDERLINE** — mixed signals or vague scope
- **WEAK FIT** — an EA/admin role rebranded as CoS (rampant in this niche)

Each verdict comes with a one-sentence reason and a detected remote policy, and the
dashboard gets a "Hide weak matches" toggle.

Setup: get an API key at console.anthropic.com, then in your repo go to
Settings → Secrets and variables → Actions → New repository secret, name it
`ANTHROPIC_API_KEY`, and paste the key. That's it — the next run screens everything.

Cost: roughly 1–2k tokens per listing on Haiku, and each listing is screened exactly
once, so expect pennies per month. Without the key, everything still works — you just
don't get fit badges (screening auto-retries once a key is added). Tunables via env
vars in the workflow: `SCREEN_MODEL` (default `claude-haiku-4-5-20251001`) and
`SCREEN_MAX_PER_RUN` (default 25, a cost guard for the big first run).

Screening is fail-safe by design: API errors or malformed replies just leave the
listing unscreened and it's retried next run. Job descriptions are only held in
memory during a run — they're never committed to the repo.

## Self-expanding watch list (automatic board discovery)

Roughly once a day, the tracker uses your existing Anthropic API key to run web
searches (restricted to jobs.ashbyhq.com, jobs.lever.co, and the Greenhouse job
sites) for your title keywords. Every company found gets adopted into the watch
list automatically and permanently — its board is then fetched through the proper
ATS API like any hand-added company, every run, until the end of time.

- No new accounts or secrets needed; it reuses `ANTHROPIC_API_KEY`.
- Discovered boards live in `data/jobs.json` under `discovered` (separate from
  `companies.json`, which remains yours to curate by hand).
- A discovered slug that turns out not to exist (404) is dropped automatically;
  transient network errors don't drop anything.
- Coverage compounds: each day's searches surface different postings, and every
  adoption is permanent, so the watched-boards count grows week over week.
- Cost: up to 6 web searches once per day (web search is billed at $10 per 1,000
  searches, plus small Haiku token costs) — roughly $2–3/month. Tunables via env
  vars in the workflow: `DISCOVERY_INTERVAL_HOURS` (default 20),
  `DISCOVERY_MAX_SEARCHES` (default 6), `DISCOVERY_MODEL`.

Hand-adding companies still matters for guaranteed coverage of companies you care
about most; discovery + Adzuna handle the long tail you'd never find yourself.

## Catch-all market search via Adzuna (optional, recommended)

The company list only sees companies you've added. Adzuna is a job aggregator that
indexes thousands of job sites — adding its free API gives the tracker a market-wide
phrase search for your title keywords, catching roles at companies you've never heard
of, including many postings that also appear on LinkedIn and BuiltIn.

Setup: sign up free at developer.adzuna.com → create an application → you get an
**App ID** and an **App Key**. Add both as repository secrets (Settings → Secrets and
variables → Actions → New repository secret): one named `ADZUNA_APP_ID`, one named
`ADZUNA_APP_KEY`.

Notes:
- Results are deduplicated against your direct ATS boards by company + title, but the
  same posting syndicated to multiple sites can occasionally slip through with a
  different company spelling.
- Adzuna descriptions are snippets, so screening verdicts for adzuna-sourced jobs are
  based on less text — treat them as a first pass and read the posting.
- Default market is the US; set the `ADZUNA_COUNTRY` env var in the workflow (e.g.
  `gb`, `ca`, `de`) to change it.

## Widening the net with keywords

Title matching is literal: a "Strategy & Operations Lead" posting will not match
"chief of staff". If you want adjacent roles, add phrases to `title_keywords` in
`companies.json`, e.g. `"business operations"`, `"founder's office"`,
`"strategy & operations"`. Each phrase is also searched market-wide on Adzuna, so
add them thoughtfully — broader phrases mean more borderline results (the LLM
screening badges help sort those).

## Why not LinkedIn / BuiltIn directly?

Neither offers a public API, and both actively block automated scraping (it's also
against their terms of service), so a scraper would be unreliable and short-lived.
The practical combination that gets you equivalent coverage:
1. This tracker's direct ATS boards (deepest, fastest signal for companies you watch)
2. The Adzuna catch-all (market-wide; overlaps heavily with LinkedIn/BuiltIn content)
3. LinkedIn's and BuiltIn's own saved-search email alerts, set up once on their sites

## Curating `companies.json` (the important part)

The seed list is a starting guess — some slugs may be wrong or companies may have
switched ATS providers. Board errors are logged per company and never crash the run,
so a bad slug just means that one company is skipped (check the Action's logs for
`warn:` lines). To verify or add a company, open its careers page and look at a job
posting's URL:

| URL looks like | ATS | Slug |
|---|---|---|
| `boards.greenhouse.io/acme/...` or `job-boards.greenhouse.io/acme` | greenhouse | `acme` |
| `jobs.lever.co/acme/...` | lever | `acme` |
| `jobs.ashbyhq.com/acme/...` | ashby | `acme` (case-sensitive) |

Then add `{ "slug": "acme", "name": "Acme" }` to the matching list in
`companies.json`, commit, done.

Good places to *discover* companies to add: VC portfolio job boards (a16z, Sequoia,
First Round), Y Combinator's Work at a Startup, and Wellfound. When you spot a CoS
posting there, add the company here so it's tracked permanently.

You can also broaden `title_keywords` (e.g. add `"business operations"` or
`"founder's office"`) to widen the net.

## Run locally

```
pip install -r requirements.txt
python scrape.py            # fetches boards, updates data/jobs.json
python build_dashboard.py   # regenerates docs/index.html
open docs/index.html
```

## How it works

```
scrape.py            discover new boards (Claude web search) → fetch boards + Adzuna market search → filter titles → dedupe → screen via Claude → data/jobs.json
build_dashboard.py   data/jobs.json → docs/index.html (static, self-contained)
.github/workflows/   cron every 6h → run both → commit changes back to the repo
```

- New listings get a `first_seen` timestamp; the dashboard badges anything from the
  last 7 days as **NEW**.
- Listings that vanish from a board are marked **closed** (kept for history) — but
  only if that board was successfully reached that run, so a network hiccup never
  falsely closes jobs. If a listing reappears, it's automatically reopened.

## Ideas for later

- **Push alerts**: if you ever want pings, add a step that posts new listings to a
  Slack/Discord webhook or sends an email — the new-vs-seen diff logic already exists.
