# AI Steward Dashboard

A one-stop dashboard that helps Australian Public Servants keep their finger on the
pulse of AI: changes to the AI policies and terms of service they rely on, the news
around them, and AI incidents — all checked daily.

- **Policy watch** — a curated set of government and private-sector policy pages is
  checked daily; genuine changes in wording are summarised and prioritised by Google
  Gemini, and everything else (reformatting, block pages, flip-flops) is filtered out
  before it can raise an alert.
- **News** — Australian government announcements, public-sector and technology media,
  overseas regulators and the AI providers themselves, filtered to AI, ranked for
  relevance to APS work, and folded so one story appears once.
- **AI incidents** — the OECD AI Incidents Monitor, sliced to incidents in Australia,
  government-sector incidents worldwide, and the most widely reported.

🔗 **Live dashboard:** https://thomas-amann-ipaustralia.github.io/ai-steward-dashboard

---

## How it works

The monitor is a chain of cheap gates in front of one expensive call:

```
probe → validate → normalise + hash → diff → cosmetic gate → fingerprint → LLM
```

Each gate exists because skipping it produced a false alert. In order:

1. **Probe** — a conditional `GET` carrying `If-None-Match` / `If-Modified-Since`.
   A `304` ends the check for that document: no browser, no extraction, no hash.

2. **Fetch and extract** — `requests` plus `trafilatura` by default. Headless
   Chrome is the fallback only, for URLs marked `"render": true` in
   `policy_sets.json` and for salvaging a plain fetch that came back unusable.

3. **Validate** — a capture must be at least ~500 characters, must not match a
   block-page signature, and must be within 60–250% of the stored length for
   that URL. A capture that fails is recorded as a `suspect_scrape`: the stored
   snapshot is left alone and nothing reaches the model.

4. **Normalise and hash** — whitespace, HTML entities, Unicode form, typographic
   quotes and a per-source noise list are collapsed *before* hashing, per URL
   rather than per policy set. Normalisation is idempotent.

5. **Diff and the cosmetic gate** — `difflib.unified_diff` over the normalised
   text, comparing *wording*: blocks that differ only in spacing, line wrapping,
   quote or dash style, capitalisation or how a link is written are set aside
   before the diff is built, and a page returning to a version already seen is
   recorded as a revert rather than re-analysed. Nothing substantive left stops
   here: no model call, `last_amended` untouched.

6. **Fingerprint** — a regex scan of the changed lines only, tagging money,
   dates, percentages, section references, obligations and a steward watchlist.
   It is passed to the model as context and never used as a veto.

7. **Analysis** — only the diff is sent, not two 50,000-character documents. The
   response must satisfy a schema (`verdict`, `summary`, `analysis`, `priority`,
   with both enums checked) that is also enforced by the API; one retry, then log
   and skip. An overloaded model is waited out rather than counted as a failure.
   The model may return `no_material_change`, in which case the set is not badged
   and `last_amended` does not move. The analysis timestamp is stamped in code.

Alongside that, each run writes a record per document to `runs.jsonl`, a source
health report to `health.json`, and an index over the archived analyses to
`history.json`.

**News and incidents (`news_watch.py`)** — RSS/Atom feeds and the OECD AI Incidents
Monitor API, through the same shape of pipeline: a window, canonical-URL dedupe,
live blogs and podcasts dropped, an AI-in-the-headline gate for general feeds,
keyword relevance scoring, links to the monitored policies, and repeats folded —
all before one batched Gemini pass that writes a TLDR, refines the score and folds
the remaining repeat coverage of the same story. See [`BACKEND.md`](BACKEND.md#news-and-ai-incidents).

**Dashboard (`src/`)** — A React single-page app with five views: an **Overview**
briefing (a one-paragraph summary of what's new since your last visit, a **review
queue** of material policy changes that you mark off as you read them, a timeline of
every source's changes, top news and Australian incidents, and a copyable weekly
briefing); **Policy watch** (every source on one timeline, then per policy: the
diff with changed words highlighted, which document changed, a month of daily checks,
the change history, related news); **News** and **AI incidents** (filterable,
shareable views with a per-day chart); and **Sources** (every source's daily read
status, and a funnel of how many would-be changes were filtered). Policy changes are
the only thing the dashboard asks anyone to act on; news relevance is shown as a
quiet signal, never as a call to action. Press Ctrl/⌘+K anywhere to search it all.

The whole pipeline is orchestrated by GitHub Actions, which runs the monitor daily,
commits any new snapshots, diffs and analyses, rebuilds the React app, and deploys
it to GitHub Pages.

## What's monitored

Policy sources are configured in [`policy_sets.json`](policy_sets.json). Each entry
defines a named policy set, a category, and one or more URLs (optionally with a CSS
selector to target the relevant part of the page). The current sets cover:

- **Australian Government** — Digital.gov.au AI Policy, National Archives AI Policy,
  ACSC Information Security Manual (ISM)
- **State Government** — NSW Government AI Guidance
- **Private Sector** — Google, Anthropic, Perplexity, and Midjourney legal policies

News and incident feeds are configured in [`news_sources.json`](news_sources.json):
ABC News and Guardian Australia's AI coverage, SBS News, The Canberra Times, The
Mandarin, Government News and iTnews; The Conversation and the OECD.AI blog for
analysis; `gov.au` pages and the Prime Minister's media releases; Google News
searches for Australian public-sector AI coverage, AI regulation and AI providers'
policy changes; the UK AI Security Institute and DSIT, and the European Commission;
OpenAI, Google and Microsoft; and three slices of the OECD AI Incidents Monitor.

To monitor a new policy source, add an entry to `policy_sets.json`:

```json
{
  "setName": "Example AI Policy",
  "category": "Private Sector",
  "urls": [
    { "url": "https://example.com/terms", "selector": "article" }
  ]
}
```

## Project structure

```
main.py              # Orchestrator: sequences the gates, keeps per-document state
news_watch.py        # Orchestrator for the news and incident feed
steward/             # The gates themselves
  config.py          #   steward_config.yaml, loaded and validated at startup
  fetching.py        #   conditional GET, trafilatura, Selenium fallback
  validation.py      #   plausibility checks on a capture
  content.py         #   normalisation, hashing, document ids and labels
  diffing.py         #   unified diff, cosmetic gate, significance fingerprint
  analysis.py        #   the Gemini call and its schema contract
  runlog.py          #   one record per document per run
  health.py          #   source status and alerting
  history.py         #   the index over logs/
  feeds.py           #   RSS/Atom parsing and the OECD AIM API
  news.py            #   news gates: window, dedupe, AI gate, relevance, cross-links
  news_enrichment.py #   the batched model pass over news items
steward_config.yaml  # Thresholds, watchlist, news vocabulary — validated, fail-fast
policy_sets.json     # Configuration of monitored policy sources
news_sources.json    # Configuration of news and incident feeds
hashes.json          # Per-set and per-document state, read directly by the app
health.json          # Which sources are actually being read successfully
history.json         # Index over the archived analyses in logs/
runs.jsonl           # Per-document run log: outcomes, tokens, durations
snapshots/           # Latest normalised text — per set, and per document
diffs/               # Unified diff behind the most recent analysis per set
analysis/            # Latest AI analysis (JSON) per policy set
logs/                # Archived snapshots, diffs and analyses of past versions
news/                # feed.json (what the app reads), archive/, state.json
tests/               # Pipeline tests (stdlib unittest, no network or API key)
requirements.txt     # Python dependencies
src/                 # React dashboard (components, hooks, utils)
public/              # Static assets for the React app
.github/workflows/   # GitHub Actions automation
```

## Running locally

### Prerequisites

- Python 3.11+
- Node.js 20+
- Google Chrome — only needed for sources marked `"render": true`
- A Google Gemini API key

### Backend (scraper + analysis)

```bash
# Install Python dependencies
pip install -r requirements.txt

# Configure your environment (see .env.example)
export GEMINI_API_KEY="your-api-key"
# Optional proxy for sites with bot detection:
# export PROXY_HOST=... PROXY_PORT=... PROXY_USER=... PROXY_PASS=...

# Run a check
python main.py

# Run every gate and report what would happen, changing nothing on disk
python main.py --dry-run

# Limit the run to one policy set (skips the news feed)
python main.py --only "Anthropic Legal Policies"

# Refresh just the news and incident feed, or dry-run one feed
python news_watch.py
python news_watch.py --dry-run --only oecd-aim-australia

# Run the pipeline tests (no network, no browser, no API key needed)
python -m unittest discover -s tests
```

The script updates `hashes.json`, `health.json`, `history.json` and `runs.jsonl`,
writes to `snapshots/`, `diffs/` and `analysis/`, then refreshes `news/`. On the first run for a policy
set it captures an initial snapshot; on later runs it calls Gemini only when the
normalised content has actually changed.

Tuning lives in [`steward_config.yaml`](steward_config.yaml) — validation
thresholds, diff context, the watchlist, retention and the model name. It is
validated at startup and the run stops with a message naming the offending key
rather than proceeding on a bad value.

> **Environment variables** are read from the process environment. Copy
> [`.env.example`](.env.example) as a reference for what to set. `GEMINI_API_KEY` is
> required; the `PROXY_*` variables are optional and only used to retry sites that
> block direct scraping.

### Frontend (dashboard)

```bash
# Install Node dependencies
npm install

# Start the development server
npm start        # http://localhost:3000

# Production build
npm run build
```

The React app fetches `hashes.json`, `health.json`, `history.json`, `analysis/`,
`diffs/`, `snapshots/` and `news/feed.json` from the site root, so these data files need to be
present in the build for the dashboard to display content.

```bash
# Frontend tests
npm test -- --watchAll=false
```

## Automation

Two GitHub Actions workflows live in `.github/workflows/`:

- **`update_checker.yml`** — Runs daily at midnight UTC (and on manual dispatch or
  pushes to `main` that touch app/config files). It installs Chrome and
  dependencies, runs the pipeline tests, runs `main.py` and then `news_watch.py`,
  commits any changes,
  opens or updates a `source-health` issue when a source is failing, builds the
  React app, and deploys it to GitHub Pages. Requires the `GEMINI_API_KEY` secret
  (and optional `PROXY_*` secrets).
- **`generate_lockfile.yml`** — A manual helper that regenerates
  `package-lock.json`.

## License

Released under the [MIT License](LICENSE).
