# AI Steward Dashboard

A monitoring tool that helps Australian Public Servants keep track of changes to
GenAI platform policies, terms of service, and relevant AI governance guidance.

The dashboard automatically watches a curated set of government and private-sector
policy pages, detects when they change, uses Google Gemini to summarise and
prioritise each change, and publishes the results as a searchable web dashboard.

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
   text. An empty diff stops here: no model call, `last_amended` untouched.

6. **Fingerprint** — a regex scan of the changed lines only, tagging money,
   dates, percentages, section references, obligations and a steward watchlist.
   It is passed to the model as context and never used as a veto.

7. **Analysis** — only the diff is sent, not two 50,000-character documents. The
   response must satisfy a schema (`verdict`, `summary`, `analysis`, `priority`,
   with both enums checked); one retry, then log and skip. The model may return
   `no_material_change`, in which case the set is not badged and `last_amended`
   does not move. The analysis timestamp is stamped in code.

Alongside that, each run writes a record per document to `runs.jsonl`, a source
health report to `health.json`, and an index over the archived analyses to
`history.json`.

**Dashboard (`src/`)** — A React single-page app that leads with the diff, shows
which document in a set changed, surfaces sources that are failing to read, and
renders the archive as a timeline.

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

To monitor a new source, add an entry to `policy_sets.json`:

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
steward_config.yaml  # Thresholds, watchlist, retention — validated, fail-fast
policy_sets.json     # Configuration of monitored policy sources
hashes.json          # Per-set and per-document state, read directly by the app
health.json          # Which sources are actually being read successfully
history.json         # Index over the archived analyses in logs/
runs.jsonl           # Per-document run log: outcomes, tokens, durations
snapshots/           # Latest normalised text — per set, and per document
diffs/               # Unified diff behind the most recent analysis per set
analysis/            # Latest AI analysis (JSON) per policy set
logs/                # Archived snapshots, diffs and analyses of past versions
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

# Limit the run to one policy set
python main.py --only "Anthropic Legal Policies"

# Run the pipeline tests (no network, no browser, no API key needed)
python -m unittest discover -s tests
```

The script updates `hashes.json`, `health.json`, `history.json` and `runs.jsonl`,
and writes to `snapshots/`, `diffs/` and `analysis/`. On the first run for a policy
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
`diffs/` and `snapshots/` from the site root, so these data files need to be
present in the build for the dashboard to display content.

```bash
# Frontend tests
npm test -- --watchAll=false
```

## Automation

Two GitHub Actions workflows live in `.github/workflows/`:

- **`update_checker.yml`** — Runs daily at midnight UTC (and on manual dispatch or
  pushes to `main` that touch app/config files). It installs Chrome and
  dependencies, runs the pipeline tests, runs `main.py`, commits any changes,
  opens or updates a `source-health` issue when a source is failing, builds the
  React app, and deploys it to GitHub Pages. Requires the `GEMINI_API_KEY` secret
  (and optional `PROXY_*` secrets).
- **`generate_lockfile.yml`** — A manual helper that regenerates
  `package-lock.json`.

## License

Released under the [MIT License](LICENSE).
