# How the backend works

This is the detailed explainer behind the summary in `README.md` and
`CLAUDE.md`. It covers the full pipeline stage by stage, every data file the
pipeline reads or writes, and a walkthrough for adding a new monitored
source.

There is no server and no database. `main.py` runs once per invocation (daily,
via GitHub Actions), reads and writes plain files in the repo, and exits. The
React frontend later fetches those same files over HTTP once the repo is
deployed to GitHub Pages. If you're picturing a long-running process — there
isn't one.

## The mental model

One **policy set** (an entry in `policy_sets.json`) is a named, categorised
group of one or more **documents** (URLs). A policy set is the unit the
dashboard shows and the unit Gemini analyses. A document is the unit that gets
fetched, validated, normalised and hashed.

Splitting the two matters: if a policy set has three URLs and only one of
them changes, the pipeline diffs only that one document, tells Gemini which
document changed, and doesn't touch the state of the other two. Early
versions of this tool hashed a whole set as one blob, so one URL going down
looked identical to the whole set changing — that bug is why the per-document
split exists (see `main.py`'s `seed_documents_from_legacy`, which migrates old
single-hash state into the new per-document shape on first run after an
upgrade).

## The pipeline, gate by gate

For each document in each policy set, `main.py:process_document` runs this
sequence. Everything is a cheap gate guarding one expensive step (the Gemini
call), and any gate can stop the document from going further.

### 1. Probe (`steward/fetching.py`)

A conditional `GET` carrying `If-None-Match` (from the stored `etag`) and
`If-Modified-Since` (from the stored `last_modified`). A `304 Not Modified`
response ends the check for that document immediately — no HTML parsing, no
extraction, no hash, no diff, and `consecutive_failures` resets to 0. This is
the common case on most days for most sources.

Set `fetch.disable_conditional_get: true` in `steward_config.yaml` to force a
full download every time (useful for debugging a source that's serving stale
conditional responses).

### 2. Fetch and extract (`steward/fetching.py`)

If the probe didn't return 304, the page is downloaded and turned into plain
text:

- **Default path**: `requests.get(...)` for the HTML, then
  `trafilatura.extract(...)` to pull the readable content and discard
  navigation/boilerplate. If the URL has a `"selector"` in `policy_sets.json`,
  BeautifulSoup narrows the HTML to that CSS selector first and trafilatura
  runs on the narrowed fragment (falling back to raw `get_text()` if
  trafilatura declines a short/list-like fragment).
- **Selenium (headless Chrome) fallback**: only used when the URL or its
  policy set is marked `"render": true`, or when the plain fetch came back
  empty/unusable (see `_worth_rendering` — a 404 is an answer, not a
  rendering problem, so a browser is not launched to re-read it). Selenium is
  imported lazily inside `_selenium_fetch` specifically so a run where every
  source is static HTML never pays for the import or a browser launch.
- **Proxy retry**: if `PROXY_HOST`/`PROXY_PORT`/`PROXY_USER`/`PROXY_PASS` are
  set in the environment, a direct attempt that fails is retried through the
  proxy. `"force_proxy": true` on a URL or policy set skips straight to the
  proxy (useful for a source with known bot-detection that always blocks
  direct requests).

Every attempt is retried up to `fetch.max_retries` times with
`fetch.retry_delay_seconds` between attempts, escalating from direct→proxy
and plain→rendered as needed. See `fetch_document`'s docstring for the exact
order.

### 3. Validate (`steward/validation.py`)

A freshly captured document must pass `validate_capture` before it can
overwrite anything or reach the model:

- **Not empty.**
- **Not a block/error page** — checked against `validation.failure_signatures`
  in `steward_config.yaml` (Cloudflare challenge pages, Chrome's "site can't
  be reached", rate-limit pages, etc.), matched on a case- and
  quote-folded copy of the text so a smart-quote apostrophe can't slip a
  block page past a straight-quote signature.
- **At least `validation.min_length` characters** (default 500 — a policy
  document that short isn't a policy document).
- **Within `[shrink_ratio, growth_ratio]` of the stored length for that same
  URL** (default 60%–250%), when a prior length exists.

A capture that fails any of these is recorded with status `suspect_scrape`:
the stored snapshot is left untouched, no diff is computed, no model call
happens, and `consecutive_failures` increments (which is what eventually
turns the source `degraded`/`failing` in health.json — see below). This is
the gate that stops a transient CDN error page from ever being treated as a
233-character replacement for a 57 kB terms-of-service document.

### 4. Normalise and hash (`steward/content.py`)

The validated text is **normalised** before hashing:

- CRLF → LF, HTML entities unescaped to a fixed point (handles double-escaped
  entities), Unicode NFC, zero-width characters stripped, NBSP → space.
- Any regex in `normalisation.noise_patterns` (global) or
  `normalisation.per_source_noise.<hostname>` (per-host) is stripped —
  this is where a rotating "we updated our privacy notice" banner or a
  site-wide "Effective <date> | Archived versions" line gets removed *before*
  it can look like a content change. `per_source_noise` is keyed by hostname
  (`steward/content.host_of`), not by policy-set name.
- Whitespace collapsed within lines, runs of 3+ blank lines collapsed to one.

`normalise` is idempotent — normalising an already-normalised string is a
no-op — because stored snapshots are normalised text and get re-normalised
implicitly every time they're compared against. If this weren't idempotent,
every comparison would drift.

The normalised text is SHA-256 hashed (`content_hash`). That hash, compared
against the document's stored hash from `hashes.json`, is what decides
`unchanged` vs. "needs a diff."

### 5. Diff and the cosmetic gate (`steward/diffing.py`)

If the hash changed, `difflib.unified_diff` runs between the *stored*
normalised text and the *new* normalised text, with `diff.context_lines`
lines of context either side of each change (default 3). If the resulting
diff has zero added and zero removed lines — possible if two different texts
normalise to the same string in some edge case, or as a defence-in-depth
check — the document is treated as `unchanged` and nothing proceeds further.
No model call, `last_amended` untouched.

### 6. Fingerprint (`steward/diffing.py`)

A regex scan runs over *only the changed lines* (not the whole document),
tagging things like `money`, `date`, `percentage`, `duration`,
`section_reference`, `obligation`, and any hit against
`fingerprint.watchlist` in `steward_config.yaml` (as `watchlist:<term>`
tags — e.g. `watchlist:arbitration`). These tags are handed to the model as
context in the prompt ("a pattern scan flagged: ..., treat this as a hint
about where to look, not as a conclusion") and are also stored on the diff
record. **The fingerprint never gates anything** — a real content change is
analysed regardless of whether it matches the watchlist, and a watchlist hit
never forces a change to be analysed if the diff itself was empty.

### 7. Analysis — the one expensive call (`steward/analysis.py`)

This only happens once per **policy set** per run, after every document in
that set has been through steps 1–6, and only if at least one document in the
set produced a non-empty diff (see `process_policy_set` in `main.py`). All
per-document diffs in the set are combined into one diff artefact
(`combine_diffs`), sectioned by document label, and sent to Gemini in a
single call — never the full documents, just the diff.

The prompt (`build_prompt`) tells the model which documents in the set
changed, gives it the fingerprint tags as a hint, and requires a JSON object
with exactly four keys:

```json
{
  "verdict": "material_change | no_material_change | uncertain",
  "summary": "1-2 sentences, plain language",
  "analysis": "markdown: what changed, who's affected, rights/data/liability, action required",
  "priority": "critical | high | medium | low"
}
```

The response is parsed and schema-checked (`parse_and_validate`): both enums
are checked against a fixed set of permitted values, `summary`/`analysis`
must be non-empty strings, and a `no_material_change` verdict is forced to
`priority: low` regardless of what the model said. If validation fails, one
retry is sent with the specific error appended to the prompt; if that also
fails, the analysis is logged and skipped — the document's prior hash is
restored (`_revert_changed_documents`) so the *same* diff is retried on the
next run rather than being silently lost, and `schema_failures` increments
(which can raise a health alert — see below).

The timestamp on the analysis is stamped by `main.py`, never accepted from
the model — a prior version of this tool asked the model for a date and it
invented one.

If the verdict is `no_material_change`, the policy set is **not** badged:
`last_amended`, `last_priority` and `last_verdict` are left untouched, but the
new (normalised) text still becomes the stored baseline so the same
non-material diff isn't re-sent to the model on the next run. If the verdict
is `material_change` or `uncertain`, the set *is* badged, the previous
analysis/snapshot/diff are archived into `logs/` first
(`archive_previous_version`), and the new analysis is written to
`analysis/<file_id>.json`.

## Data files

Everything below lives at the repo root or in the named directory, and is
regenerated by `main.py` (except `policy_sets.json` and
`steward_config.yaml`, which are hand-edited config). The frontend fetches
these directly over HTTP from the deployed site — there's no API layer.

| File / dir | Written by | Read by | What it is |
|---|---|---|---|
| `policy_sets.json` | you | `main.py`, frontend | The list of monitored sources — see below |
| `steward_config.yaml` | you | `steward/config.py` | Thresholds, watchlist, model, retention |
| `hashes.json` | `main.py` | frontend, `main.py` (next run) | Per-set and per-document state: hashes, timestamps, last analysis pointers, health counters |
| `health.json` | `steward/health.py` | frontend | Whether each source is actually being read successfully right now |
| `history.json` | `steward/history.py` | frontend | Index over everything archived in `logs/`, so the timeline doesn't need a directory listing (GitHub Pages doesn't serve one) |
| `runs.jsonl` | `steward/runlog.py` | analysis/debugging | One JSON line per document per run: outcome, tokens, duration, tags |
| `snapshots/<file_id>.txt` | `main.py` | frontend | Latest combined (all-documents) normalised text for a set, for the "raw text" disclosure |
| `snapshots/<file_id>/<doc_id>.txt` | `main.py` | `main.py` (next run's diff base) | Latest normalised text per document — the actual diff baseline |
| `diffs/<file_id>.diff` | `main.py` | frontend | Unified diff behind the most recent *analysed* change for a set |
| `analysis/<file_id>.json` | `main.py` | frontend | Latest AI analysis for a set |
| `logs/<file_id>_<stamp>_{analysis.json,snapshot.txt,diff.txt}` | `main.py` | `steward/history.py`, frontend (on demand) | Archived prior versions, one triple per analysed change |
| `health_alert.md` | `steward/health.py` | GitHub Actions workflow | Only written when there's something to alert on; becomes a GitHub issue |

`file_id` is `slugify_set_name(setName)` — the policy set name with
everything except letters/digits/hyphens collapsed to underscores
(`main.py:slugify_set_name`). `doc_id` is a short, stable, filesystem-safe id
derived from the URL (`steward/content.py:document_id`) — the last part of
the URL path plus an 8-char hash of the full URL, so two documents with the
same trailing path segment on different sets don't collide.

### `hashes.json` shape

```jsonc
{
  "<setName>": {
    "hash": "sha256 rollup of every document's hash, sorted by url",
    "category": "Private Sector",
    "urls": [ /* copy of the policy_sets.json entry's urls, for the frontend */ ],
    "file_id": "Example_AI_Policy",
    "last_checked": "2026-08-13T10:00:00+10:00",
    "last_amended": "2026-08-01T10:00:00+10:00",   // last time a badged change happened
    "last_priority": "medium",
    "last_verdict": "material_change",
    "last_change": { "timestamp": "...", "verdict": "...", "changed_documents": [...], "added": 12, "removed": 3, "tags": [...] },
    "last_review": { "timestamp": "...", "verdict": "...", "summary": "..." }, // most recent *analysis run*, badged or not
    "schema_failures": 0,
    "consecutive_failures": 0,
    "last_success": "2026-08-13T10:00:00+10:00",
    "status": "ok | degraded | failing",
    "documents": {
      "<url>": {
        "doc_id": "terms-of-service-a1b2c3d4",
        "label": "Terms Of Service",
        "hash": "...", "length": 43210,
        "etag": "...", "last_modified": "...",
        "extractor": "trafilatura | selector+trafilatura | selenium+trafilatura",
        "pipeline_version": 2,
        "http_status": 200, "fetch_ms": 812,
        "consecutive_failures": 0,
        "last_checked": "...", "last_success": "...", "last_error": "",
        "status": "unchanged | changed | new | rebaselined | not_modified | suspect_scrape | fetch_failed"
      }
    }
  }
}
```

`last_amended` only moves for a `material_change`/`uncertain` verdict —
that's the field the "how long since this actually changed" UI is built on.
`last_review` moves any time an analysis ran, badged or not, which is why
it's a separate field from `last_change`.

## Configuration reference (`steward_config.yaml`)

Loaded and strictly validated by `steward/config.py` at startup — an unknown
key, wrong type, or out-of-range value stops the run immediately with a
message naming the offending key (`ConfigError`). There is no silent
fallback to a default for a key that's present but wrong. Sections:

- **`model`** — the Gemini model name used for analysis (e.g.
  `gemini-2.5-flash`).
- **`fetch`** — timeouts, retry count/delay, Selenium page-load timeout,
  `disable_conditional_get`, the `User-Agent` string.
- **`validation`** — `min_length`, `shrink_ratio`, `growth_ratio`,
  `failure_signatures` (block-page substrings).
- **`normalisation`** — `noise_patterns` (global regexes, kept empty on
  purpose — a pattern broad enough to apply everywhere is broad enough to
  eat a real amendment) and `per_source_noise` (regexes keyed by hostname).
- **`diff`** — `context_lines`, `max_diff_chars` (hard ceiling on what's sent
  to the model; longer diffs are truncated with a marker).
- **`fingerprint`** — `watchlist` (context terms, never a gate — see above).
- **`health`** — `consecutive_failure_threshold` (when a document flips to
  `failing`), `error_rate_threshold` (share of documents failing in one run
  that flags `run_error_rate`), `schema_failure_threshold`.
- **`retention`** — `log_days` (how long archives stay in `logs/` before
  `steward/history.py:prune` deletes them), `run_log_days` (same, for
  `runs.jsonl`).

## Health and alerting (`steward/health.py`)

Health is derived entirely from the per-document `consecutive_failures`
counters already in `hashes.json` — there's no separate polling. A document
is `ok` at 0 failures, `degraded` above 0, `failing` at or above
`health.consecutive_failure_threshold`. A policy set's status is the worst of
its documents. `steward/health.py:build_report` also raises a
`schema_failures` alert (the model keeps returning invalid JSON for a set)
and a `run_error_rate` alert (too large a share of *all* documents failed in
one run — a signal something systemic broke, like an IP getting blocked
everywhere).

`main.py` writes `health.json` for the frontend every run, and writes
`health_alert.md` only when `report["alerts"]` is non-empty (and deletes it
otherwise). The workflow (`.github/workflows/update_checker.yml`) turns that
file into a GitHub issue labelled `source-health`, updating the existing open
issue with a comment rather than opening a duplicate. **A source in this
state is not reporting "no changes" — the dashboard is reporting nothing
about it at all**, which is the exact failure mode this alerting exists to
surface (see `steward/health.py`'s module docstring for the incident that
motivated it).

## Testing

```bash
python -m unittest discover -s tests -v
```

`tests/test_pipeline.py` and `tests/test_run.py` are stdlib `unittest`, need
no network, browser, or `GEMINI_API_KEY`, and run in CI before `main.py` is
even invoked. They're not a coverage exercise — several pin a specific
production incident so it can't silently reoccur, most notably: normalisation
idempotency, the cosmetic-diff gate producing no model call, the size-delta
guard rejecting a real archived block-page capture
(`logs/Perplexity_AI_Legal_Policies_20260808_120221_snapshot.txt` is used as
a literal fixture), and schema validation rejecting an out-of-enum priority.
If you touch `steward/validation.py`, `steward/content.py`, or
`steward/analysis.py`, run these before anything else.

## Adding a new source

1. **Find the URL(s)** for the policy/ToS/guidance page(s) you want watched.
   A "policy set" can be one URL or several — group URLs that belong to the
   same policy family (e.g. a provider's ToS + privacy policy + AUP) into one
   set so they're diffed and analysed together and shown as one card on the
   dashboard.

2. **Add an entry to `policy_sets.json`**:

   ```json
   {
     "setName": "Example AI Policy",
     "category": "Private Sector",
     "urls": [
       { "url": "https://example.com/terms", "selector": "article" },
       { "url": "https://example.com/privacy" }
     ]
   }
   ```

   - `setName` must be unique across the file — it's the dashboard card title
     and the seed for `file_id` (`slugify_set_name`). `main.py` skips (with a
     warning, not a crash) any entry with a duplicate or missing `setName`,
     a missing `category`, or an empty/malformed `urls` list — see
     `validate_policy_sets`.
   - `category` groups sets in the sidebar. Reuse an existing one (`"Australian
     Government"`, `"State Government"`, `"Private Sector"`) unless you're
     genuinely introducing a new grouping.
   - Each URL entry supports:
     - `"selector"` (optional) — a CSS selector narrowing extraction to one
       part of the page (e.g. `"article"`, `"div.main-content"`,
       `"div[jsname='v2d3Ub']"`). **Always try to find one.** Without it,
       trafilatura extracts the whole readable page, which means nav/footer
       changes elsewhere on the site can occasionally leak into the diff.
       Open the page's DOM in a browser and look for the element wrapping
       just the policy text.
     - `"label"` (optional) — a human-readable name for this document within
       the set, shown in "which document changed" UI. Defaults to a
       title-cased version of the URL's last path segment
       (`steward/content.py:document_label`) if omitted.
     - `"render"` (optional, bool) — set `true` only if the page's policy
       text is injected by client-side JavaScript and isn't present in the
       plain HTML response (check with `curl` or view-source, not just a
       browser). This is expensive (a full headless Chrome launch) and
       should be the exception, not the default.
     - `"force_proxy"` (optional, bool) — set `true` only if you already know
       this host blocks direct requests (Cloudflare bot-challenge, etc.) and
       a proxy is configured. Otherwise the pipeline already retries through
       the proxy automatically if a direct attempt fails.
   - The same `"render"`/`"force_proxy"` keys are also honored at the
     policy-set level (applying to every URL in the set) if every document in
     a set needs the same treatment.

3. **Dry-run it before committing anything**, so a bad selector or an
   unreachable URL doesn't cost a model call or write bad state:

   ```bash
   python main.py --dry-run --only "Example AI Policy"
   ```

   `--dry-run` runs every gate — fetch, validate, normalise, diff — and logs
   what *would* happen, but writes nothing to disk. Check the log output for:
   the extractor used, the captured length (does it look like the right
   amount of text, not a nav menu or an empty page?), and whether validation
   passed. If the selector matched nothing, `fetching.py` logs a warning and
   falls back to the full page — watch for that.

4. **Run it for real** once the dry run looks right:

   ```bash
   export GEMINI_API_KEY=...
   python main.py --only "Example AI Policy"
   ```

   The **first-ever** run for a new set has nothing to compare against, so
   every document is captured as a baseline (`DOC_NEW`), a
   `no_material_change` "Initial snapshot captured" analysis is written, and
   the set is *not* badged as changed. This is expected — you're establishing
   the starting point the next run will diff against, not reporting a policy
   change on day one.

5. **Commit** `policy_sets.json` plus whatever `main.py` wrote
   (`hashes.json`, `snapshots/`, `analysis/<file_id>.json`, etc.) — or just
   let the next scheduled run of `update_checker.yml` do steps 3–5 for you by
   pushing the `policy_sets.json` change to `main` (the workflow triggers on
   pushes that touch `policy_sets.json`, among other paths).

No frontend code changes are needed — `src/hooks/usePolicySets.js` derives
the sidebar/category list entirely from what's in `hashes.json` at runtime.

### If you need per-source noise filtering

If, after a run or two, a source keeps showing "changes" that are actually a
rotating banner, a "you are viewing an archived version" line, or similar —
don't broaden `normalisation.noise_patterns` (global; affects every source).
Add a regex under `normalisation.per_source_noise.<hostname>` in
`steward_config.yaml` instead, keyed by the hostname from
`steward/content.py:host_of` (i.e. the URL's hostname, not the policy set
name). See the existing `www.perplexity.ai` and `policies.google.com` entries
for the pattern: match and strip the *whole line*
(`'(?i)^.*something.*\n?'`) rather than just the varying words, so you don't
leave a blank line behind that then becomes its own diff.

### If extraction/normalisation logic changes

If you change something in `steward/fetching.py` (what trafilatura is asked
to extract) or `steward/content.py` (normalisation rules) that would make
newly captured text incomparable with what's already stored for *every*
source — not just a new one — bump `PIPELINE_VERSION` in
`steward/__init__.py`. `main.py` uses that to detect a stale baseline and
re-baseline silently (`DOC_REBASELINED`) instead of reporting a change that
didn't really happen.

## Automation (GitHub Actions)

`.github/workflows/update_checker.yml` runs daily at 00:00 UTC (also on
manual dispatch, and on pushes to `main` touching frontend/config files). In
order: install deps → run the pipeline tests → install Chrome (for the
Selenium fallback) → run `main.py` (`continue-on-error`, so later steps can
still commit whatever was produced before a failure) → commit and push any
changed data files → open/update a `source-health` issue if
`health_alert.md` exists → fail the job if `main.py` itself exited non-zero →
build the React app → copy the data files into `build/` (note: only archived
*analyses*, not archived *snapshots*, ship to `build/logs/` — the snapshots
were the bulk of the archive's size and the timeline UI never fetches them) →
deploy to GitHub Pages.

`.github/workflows/generate_lockfile.yml` is a manual-dispatch-only helper
that regenerates `package-lock.json`.
