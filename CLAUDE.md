# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repository.

## What this is

AI Steward Dashboard: a scheduled pipeline that watches a curated list of
GenAI/AI-policy web pages, detects real content changes, has Gemini summarise
and prioritise each change, and publishes the result as a static React
dashboard on GitHub Pages. Two halves:

- **Backend** (`main.py` + `steward/`) — a Python pipeline that fetches,
  validates, diffs and analyses policy pages, and writes its output as JSON/
  text files in the repo itself (`hashes.json`, `health.json`, `history.json`,
  `snapshots/`, `diffs/`, `analysis/`, `logs/`). There is no database and no
  server — the committed files *are* the datastore.
- **Frontend** (`src/`) — a Create React App single-page app that fetches
  those same JSON files at runtime and renders them. It never talks to
  Gemini or does any fetching of its own.

Full pipeline documentation, including how to add a new monitored source,
lives in **[`BACKEND.md`](BACKEND.md)**. Read it before touching anything in
`steward/`, `main.py`, or `policy_sets.json`.

**Start with [`HANDOVER.md`](HANDOVER.md)** if you are picking up work rather
than answering a question. It records the state of the current branch, what was
deliberately left undone, and what to check on the next pipeline run.
[`REVIEW_2026-09.md`](REVIEW_2026-09.md) is the analysis it derives from and is
the backlog — its §9 is the sequenced plan.

## Commands

```bash
# Backend
pip install -r requirements.txt
export GEMINI_API_KEY=...                       # required except for --dry-run
python main.py                                  # run the full pipeline
python main.py --dry-run                        # run every gate, write nothing
python main.py --only "Anthropic Legal Policies" # limit to one policy set (repeatable)
python -m unittest discover -s tests -v          # pipeline tests — no network/browser/API key

# Frontend
npm install
npm start                                        # dev server at localhost:3000
npm run build
npm test -- --watchAll=false
```

`npm start` alone will show an empty/broken dashboard unless the data files
(`hashes.json`, `health.json`, `history.json`, `analysis/`, `diffs/`,
`snapshots/`) are present at the repo root — CRA serves the public root, and
these files are fetched from there at runtime, not bundled.

## Architecture in one paragraph

Each monitored **policy set** (`policy_sets.json`) is one or more URLs.
Every URL is fetched independently, normalised, and hashed *per document*;
only when the normalised text of at least one document in a set actually
changes does the pipeline build a diff and spend a Gemini call — one call per
changed set per run, not per URL. The model receives only the diff (not full
documents), must return a schema-checked JSON object, and may itself decide a
change is `no_material_change`. Everything upstream of that call exists to
stop something that isn't a real edit — a rotating banner, a transient block
page, whitespace — from ever reaching it. See `BACKEND.md` for the full
gate-by-gate walkthrough.

## Conventions and gotchas

- **`steward/` modules are pure and side-effect-light by design** — each one
  (`fetching`, `content`, `validation`, `diffing`, `analysis`, `health`,
  `history`, `runlog`) is independently unit-testable without network, a
  browser, or `GEMINI_API_KEY`. Keep it that way; `main.py` is the only place
  that reads/writes files and orchestrates.
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
- **Health alerts fire on transitions, not states.** A source that is still
  broken today is not news; one that broke, or recovered, is. `health_state.json`
  records what has already been reported, and anything still open is repeated at
  most once every `health.digest_days`. Don't "simplify" this back into
  alert-on-current-state — that produced thirty-five identical GitHub comments on
  one issue and is why two sources went unfixed for a month.
- **A source is turned off with `"enabled": false` and a `disabled_reason`, never
  by deletion.** Deleting a set orphans its snapshots, diffs and archived
  analyses. A disabled set keeps all of it, raises no health alert, and is shown
  on the dashboard as "not currently monitored" with its reason — because a
  source nobody is checking and a source that cannot be checked need different
  responses and must not look the same.
- **A 404 is an answer, not a failure.** `fetching.GONE` is terminal — no
  render, no proxy, no retry — and surfaces as `link_rot`, which fails a
  document on the first run and raises a `source_gone` alert. It is separate
  from a fetch failure because the remedy is a person editing a URL, not a
  retry. Don't fold it back into `FAILED`.
- **An API error is not a schema failure.** `steward/analysis.py` retries a
  failed *call* with backoff and a bad *answer* with a correction, and only the
  second counts toward `schema_failures`. Conflating them reported a Gemini 503
  as the model returning invalid JSON. `analyse_change` takes a `client` (and a
  `sleep`) so it is testable without the SDK installed — keep the
  `from google import genai` inside the `client is None` branch.
- **The fingerprint watchlist (`fingerprint.watchlist` in
  `steward_config.yaml`) is context for the model, never a gate.** A genuine
  content change is always analysed, whether or not it matches anything on
  the watchlist. Do not wire it into a skip/veto path.
- **`hashes.json`, `health.json`, `health_state.json`, `history.json`,
  `runs.jsonl`, `snapshots/`, `diffs/`, `analysis/`, `logs/` are pipeline
  output, not source.** They're committed so GitHub Pages has something to serve
  and so history survives between runs, but they're regenerated by `main.py` /
  the workflow — don't hand-edit them except to fix a specific corrupted entry,
  and never hand-craft an `analysis/*.json` or `logs/*_analysis.json` file (the
  frontend and `steward/history.py` both assume its shape came from
  `steward/analysis.py`). **The sanctioned exception is `scripts/`**: a
  pre-upgrade analysis carrying a hallucinated date, or a false positive that no
  future run will overwrite, can only be fixed in place. Do it with a
  re-runnable, `--dry-run`-able script that writes the shape
  `steward/analysis.py` produces and archives the original — not by hand, and
  not ad hoc.
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
| `steward/runlog.py` | Appends `runs.jsonl` |
| `steward/policy_sets.py` | Loads/validates `policy_sets.json`; the one validator any writer must use |
| `policy_sets.json` | **The list of monitored sources — edit this to add one** |
| `steward_config.yaml` | Thresholds, watchlist, model name, retention |
| `scripts/` | One-off but re-runnable repairs to committed pipeline output |
| `tests/` | stdlib `unittest`, no network/browser/API key |
| `src/` | React dashboard; `src/hooks/*` fetch the pipeline's output JSON |
| `.github/workflows/update_checker.yml` | Daily run → commit → build → deploy to Pages |

## Adding a new monitored source

Short version: add an entry to `policy_sets.json`, then `python main.py
--dry-run --only "Your New Set"` to sanity-check extraction before running for
real. Full walkthrough, including selector/render/proxy options and what the
first run does, is in **[`BACKEND.md`](BACKEND.md#adding-a-new-source)**.
