# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repository.

## What this is

AI Steward Dashboard: a one-stop, scheduled dashboard for Australian Public
Servants. It watches a curated list of GenAI/AI-policy web pages, detects real
content changes and has Gemini summarise and prioritise each one; alongside
that it gathers AI news and OECD AI Incidents Monitor records, filtered and
ranked for relevance to APS work. Everything is published as a static React
dashboard on GitHub Pages. Two halves:

- **Backend** — two Python orchestrators over the pure modules in `steward/`:
  `main.py` fetches, validates, diffs and analyses policy pages
  (`hashes.json`, `health.json`, `history.json`, `snapshots/`, `diffs/`,
  `analysis/`, `logs/`), and `news_watch.py` builds the news and incident feed
  (`news/`). There is no database and no server — the committed files *are*
  the datastore.
- **Frontend** (`src/`) — a Create React App single-page app that fetches
  those same JSON files at runtime and renders them. It never talks to
  Gemini or does any fetching of its own.

Full pipeline documentation, including how to add a new monitored source or
news feed, lives in **[`BACKEND.md`](BACKEND.md)**. Read it before touching
anything in `steward/`, `main.py`, `news_watch.py`, `policy_sets.json` or
`news_sources.json`.

## Commands

```bash
# Backend
pip install -r requirements.txt
export GEMINI_API_KEY=...                       # required except for --dry-run
python main.py                                  # policies, then the news feed
python main.py --dry-run                        # run every gate, write nothing
python main.py --only "Anthropic Legal Policies" # one policy set (repeatable; skips news)
python main.py --skip-news                      # policies only (what CI runs)
python news_watch.py [--dry-run] [--only FEED_ID] [--no-enrich]  # news and incidents only
python -m unittest discover -s tests -v          # pipeline tests — no network/browser/API key

# Frontend
npm install
npm start                                        # dev server at localhost:3000
npm run build
npm test -- --watchAll=false
```

`npm start` alone will show an empty/broken dashboard unless the data files
(`hashes.json`, `health.json`, `history.json`, `analysis/`, `diffs/`,
`snapshots/`, `news/feed.json`) are present at the repo root — CRA serves the public root, and
these files are fetched from there at runtime, not bundled.

## Architecture in one paragraph

Each monitored **policy set** (`policy_sets.json`) is one or more URLs.
Every URL is fetched independently, normalised, and hashed *per document*;
only when the normalised text of at least one document in a set actually
changes does the pipeline build a diff and spend a Gemini call — one call per
changed set per run, not per URL. The comparison is of wording: blocks that
differ only typographically are set aside (`cosmetic`), and a return to a
recently seen version is recorded as `reverted`, neither reaching the model.
The model receives only the diff (not full documents), must return a
schema-checked JSON object, and may itself decide a change is
`no_material_change`. Everything upstream of that call exists to stop
something that isn't a real edit — a rotating banner, a transient block page,
whitespace, a mis-decoded dash, a CDN serving two variants — from ever
reaching it. The news side mirrors this: window → canonical-URL dedupe →
format gate (live blogs, podcasts) → AI-in-the-headline gate → keyword
relevance → fold repeats → one batched model pass. The gates are the cost
control: keep anything a keyword or pattern can decide out of the prompt. See `BACKEND.md` for the
full gate-by-gate walkthrough.

## Conventions and gotchas

- **`steward/` modules are pure and side-effect-light by design** — each one
  (`fetching`, `content`, `validation`, `diffing`, `analysis`, `health`,
  `history`, `runlog`, `feeds`, `news`, `news_enrichment`) is independently
  unit-testable without network, a browser, or `GEMINI_API_KEY`. Keep it that
  way; `main.py` and `news_watch.py` are the only places that read/write files
  and orchestrate.
- **`diffing.canonical` is for comparison only** — it folds case, quotes,
  dashes, link decoration and whitespace so the cosmetic gate can compare
  wording. Never store or display its output, and don't widen it to fold
  anything that can carry meaning (numbers, words, punctuation other than
  spacing around it).
- **`steward/content.normalise` must stay idempotent** —
  `normalise(normalise(t)) == normalise(t)`. Stored snapshots are already
  normalised; re-normalising them on the next comparison must be a no-op or
  every diff drifts. There's a test that pins this
  (`tests/test_pipeline.py`, `NormalisationIsIdempotent`).
- **Bump `PIPELINE_VERSION` in `steward/__init__.py`** whenever a change to
  extraction or normalisation would make a freshly captured document
  incomparable with what's already stored (e.g. changing what `trafilatura`
  extracts, editing global noise patterns, changing the hashing scheme).
  `main.py` uses this to re-baseline instead of reporting a change that never
  happened — see `process_document`'s `stale_pipeline` check.
- **`steward_config.yaml` is validated at startup, fail-fast**
  (`steward/config.py`). An unknown key, wrong type, or out-of-range value
  stops the run with a message naming the offending key. Don't add a config
  knob by reading `os.environ` or hardcoding a constant in `main.py` — add a
  field to the relevant dataclass in `steward/config.py`, wire it into
  `validate()`, and document it in `steward_config.yaml`'s comments.
- **News and newsletter text is untrusted input.** It goes into a prompt
  fenced and labelled as data, the model's output is validated against the ids
  actually sent, and TLDRs are rendered as plain text. Store headlines, links,
  short excerpts and our own summaries — never article bodies or remote
  images (it's third-party copyright on a public site).
- **The fingerprint watchlist (`fingerprint.watchlist` in
  `steward_config.yaml`) is context for the model, never a gate.** A genuine
  content change is always analysed, whether or not it matches anything on
  the watchlist. Do not wire it into a skip/veto path.
- **`hashes.json`, `health.json`, `history.json`, `runs.jsonl`, `snapshots/`,
  `diffs/`, `analysis/`, `logs/`, `news/` are pipeline output, not source.** They're
  committed so GitHub Pages has something to serve and so history survives
  between runs, but they're regenerated by `main.py` / the workflow — don't
  hand-edit them except to fix a specific corrupted entry, and never hand-craft
  an `analysis/*.json` or `logs/*_analysis.json` file (the frontend and
  `steward/history.py` both assume its shape came from `steward/analysis.py`).
- **Tests use a real archived capture as a fixture**
  (`tests/test_pipeline.py` reads `logs/Perplexity_AI_Legal_Policies_
  20260807_125653_snapshot.txt` and its 8 August successor) to pin the
  validation gate that stopped a real false-positive incident. If you touch
  `steward/validation.py`, run these tests — they're regression tests for a
  production incident, not synthetic examples.
- **No inline `# removed`/back-compat comments, no speculative abstractions**
  — this codebase already follows that discipline (see the module docstrings
  explaining *why*, not *what*); match it in new code.
- **Frontend fetches, never fabricates.** `src/hooks/*` fetch the JSON files
  described above with a cache-busting query param and treat `health.json`
  as supplementary (its absence must not blank the dashboard). Follow that
  pattern for any new hook: a missing/failed optional file degrades a
  section, it doesn't break the page.

## Where things are

| Path | What |
|---|---|
| `main.py` | Orchestrator — sequences the gates per document/set, writes all output files |
| `steward/config.py` | Loads + validates `steward_config.yaml` |
| `steward/fetching.py` | Conditional GET, trafilatura extraction, Selenium fallback |
| `steward/validation.py` | Plausibility checks on a capture (`suspect_scrape` gate) |
| `steward/content.py` | Normalisation, hashing, document ids/labels |
| `steward/diffing.py` | Unified diff, cosmetic gate, watchlist fingerprint |
| `steward/analysis.py` | The Gemini call, prompt, schema validation/retry |
| `steward/health.py` | Per-source health status and GitHub-issue alert body |
| `steward/history.py` | Builds `history.json` from `logs/` |
| `steward/runlog.py` | Appends `runs.jsonl`; per-set activity summary for `health.json` |
| `news_watch.py` | Orchestrator for the news/incident feed — writes `news/` |
| `steward/feeds.py` | RSS/Atom parsing (stdlib), OECD AI Incidents Monitor API |
| `steward/news.py` | News gates: window, canonical ids, AI gate, relevance, cross-links, story folding |
| `steward/news_enrichment.py` | Batched Gemini TLDR/relevance/same-story pass, schema-validated |
| `policy_sets.json` | **The list of monitored sources — edit this to add one** (`keywords` links news to a set) |
| `news_sources.json` | **The list of news and incident feeds — edit this to add one** |
| `steward_config.yaml` | Thresholds, watchlist, model name, retention |
| `tests/` | stdlib `unittest`, no network/browser/API key |
| `src/` | React dashboard (Overview, Policy watch, News, AI incidents, Sources); `src/hooks/*` fetch the pipeline's output JSON |
| `.github/workflows/update_checker.yml` | Daily run → commit → build → deploy to Pages |

## Adding a new monitored source

Short version: add an entry to `policy_sets.json`, then `python main.py
--dry-run --only "Your New Set"` to sanity-check extraction before running for
real. Full walkthrough, including selector/render/proxy options and what the
first run does, is in **[`BACKEND.md`](BACKEND.md#adding-a-new-source)**.

For a news feed: add an entry to `news_sources.json`, then `python
news_watch.py --dry-run --only your-feed-id` — see
**[`BACKEND.md`](BACKEND.md#adding-a-feed)**.
