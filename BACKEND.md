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
- **Hosts that refuse plain HTTP**: several gov.au hosts (digital.gov.au,
  naa.gov.au, cyber.gov.au, protectivesecurity.gov.au) sit behind a bot
  manager that lets Chrome through but holds a `requests` connection open
  until `fetch.timeout_seconds` expires. On 25 September 2026 that was 31
  documents at 30 seconds each — 15 of the run's 18 minutes. A
  `FetchSession`, created once per run, remembers such hosts: when a plain
  GET is refused and the browser then succeeds, the document's
  `plain_blocked_at` is stamped, and later documents on that host (in this
  run, and in runs within `fetch.blocked_host_recheck_days`) go straight to
  the browser. Each host's re-check is staggered by a few days so that
  hosts first seen together are not all re-probed on the same day. The
  session also keeps **one** Chrome open for the whole run instead of
  launching one per page.
- **Proxy retry**: if `PROXY_HOST`/`PROXY_PORT`/`PROXY_USER`/`PROXY_PASS` are
  set in the environment, a direct attempt that fails is retried through the
  proxy. `"force_proxy": true` on a URL or policy set skips straight to the
  proxy. The proxy is optional: the 25 September run used it for none of
  its 76 documents.
- **Internet Archive fallback**: when every live route has failed, the
  Wayback Machine's availability API
  (`https://archive.org/wayback/available?url=…`) is asked for its newest
  capture, and the capture's original bytes (the `id_` form) are extracted
  like a live page. It is used only if it was captured after the document's
  last successful read and within `fetch.archive_max_age_days`, so it can
  never report a change backwards. The record carries `route: "archive"`
  and `archived_at`, and the dashboard says the page was read from the
  archive. Set `fetch.archive_fallback: false` to turn it off.
- **PDFs**: a response that is a PDF (by `Content-Type` or its `%PDF-`
  magic) is read with `pypdf` rather than trafilatura.

Every attempt is retried up to `fetch.max_retries` times with
`fetch.retry_delay_seconds` between attempts, escalating from direct→proxy
and plain→rendered as needed, then to the archive. Each document records the
`route` that produced its text (`plain`, `render` or `archive`). See
`fetch_document`'s docstring for the exact order.

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

The size-delta check only runs against a stored baseline that itself passes
the absolute checks. A baseline that is a block page or a stub (digital.gov.au
spent months stored as a 347-character Chrome error page) is ignored, and the
first plausible capture re-baselines the document (`DOC_REBASELINED`, reason
"stored baseline was not a valid capture") instead of being rejected forever
for "growing" fifty-fold.

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

### 5. Revert check (`main.py`)

Each document remembers the last `diff.revert_memory` hashes it has held
(`previous_hashes` in `hashes.json`, default 5). A capture whose hash matches
one of them is going *back* to a version already seen — the day-after-day
flip-flop a CDN serving two variants, or an A/B test, produces. It is recorded
as `reverted`, becomes the baseline, and is **not** re-analysed; the set's
`last_review` says which document reverted, and the set is not badged.

### 6. Diff and the cosmetic gate (`steward/diffing.py`)

If the hash changed, the cosmetic gate decides whether the *wording* did.
Each changed block of lines is reduced to a canonical form
(`diffing.canonical`): Unicode NFKC, curly quotes and every dash folded to
ASCII, case folded, `https://`/`www.`/trailing slashes dropped from links,
all whitespace — line breaks included — collapsed, and spaces around
punctuation removed. A block whose canonical form did not move is restored
to its stored wording before the diff is built; matching runs are also peeled
off the edges of larger blocks, so a re-wrapped paragraph next to a real edit
leaves only the edit. `canonical` is for comparison only and is never stored.

Then `difflib.unified_diff` runs between the stored text and that
cosmetics-restored text, with `diff.context_lines` lines of context (default
3). If nothing substantive is left, the document is recorded as `cosmetic`:
the new text becomes the baseline, `cosmetic_lines` says how much moved, and
there is no model call and no badge. Replayed against the archive, this gate
stops four of the six August–September 2026 model calls that came back
`no_material_change` (Google's em-dash spacing ×3, an NSW link gaining
`https://`); both genuine amendments in that period still reach the model.

A related fix sits upstream in `fetching.decode_body`: a response without a
declared charset is decoded as UTF-8 rather than requests' ISO-8859-1
default, which is what had Google's page alternating between `—` and `â`.

### 7. Fingerprint (`steward/diffing.py`)

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

### 8. Analysis — the one expensive call (`steward/analysis.py`)

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

The same schema is passed to the API as a `response_schema`, so the model is
constrained to it rather than merely asked; the response is still parsed and
schema-checked (`parse_and_validate`): both enums
are checked against a fixed set of permitted values, `summary`/`analysis`
must be non-empty strings, and a `no_material_change` verdict is forced to
`priority: low` regardless of what the model said. If validation fails, one
retry is sent with the specific error appended to the prompt; if that also
fails, the analysis is logged and skipped — the document's prior hash is
restored (`_revert_changed_documents`) so the *same* diff is retried on the
next run rather than being silently lost, and `schema_failures` increments
(which can raise a health alert — see below).

An overloaded or rate-limited API (HTTP 429/5xx) is waited out with a backoff
(15 s, 45 s, 90 s) inside a single attempt rather than spending the one
schema retry — two of the three "schema failures" in September 2026 were a
503 retried within the same second. If the model stays unavailable the run
records `api_unavailable`, restores the prior hashes so the change is retried
next run, and does **not** count it towards `schema_failures`.

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
| `news_sources.json` | you | `news_watch.py` | The news and incident feeds — see [News and AI incidents](#news-and-ai-incidents) |
| `news/feed.json` | `news_watch.py` | frontend | News and incident items inside the window, plus per-feed health |
| `news/archive/YYYY-MM.json` | `news_watch.py` | — | Items that aged out of the window, by month published |
| `news/state.json` | `news_watch.py` | `news_watch.py` (next run) | Per-feed ETag/Last-Modified and ids already seen; not deployed |
| `transparency/statements.json` | `transparency_watch.py` | frontend, `transparency_watch.py` (next run) | The register's state and every statement's: agency, portfolio, mandatory/voluntary, URL, the date it gives itself, last change, per-document fetch record |
| `transparency/events.json` | `transparency_watch.py` | frontend | Agencies joining, leaving or moving on the register; statements updated or reworded — newest first, kept `transparency.event_days` |
| `transparency/snapshots/<id>.txt` | `transparency_watch.py` | `transparency_watch.py` (next run's diff base) | Each statement's current normalised text; not deployed |
| `transparency/diffs/<id>.diff` | `transparency_watch.py` | frontend | The diff behind a statement's most recent summarised change |

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
        "previous_hashes": ["...", "..."],   // most recent first, for the revert check
        "status": "unchanged | changed | cosmetic | reverted | new | rebaselined | not_modified | suspect_scrape | fetch_failed"
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
  `disable_conditional_get`, the `User-Agent` string,
  `blocked_host_recheck_days` (how long a host that refused plain HTTP is
  sent straight to the browser; 0 turns it off), `archive_fallback` and
  `archive_max_age_days` (the Internet Archive fallback).
- **`validation`** — `min_length`, `shrink_ratio`, `growth_ratio`,
  `failure_signatures` (block-page substrings).
- **`normalisation`** — `noise_patterns` (global regexes, kept empty on
  purpose — a pattern broad enough to apply everywhere is broad enough to
  eat a real amendment) and `per_source_noise` (regexes keyed by hostname).
- **`diff`** — `context_lines`, `max_diff_chars` (hard ceiling on what's sent
  to the model; longer diffs are truncated with a marker), `revert_memory`
  (how many earlier versions per document the revert check remembers; 0
  disables it).
- **`fingerprint`** — `watchlist` (context terms, never a gate — see above).
- **`health`** — `consecutive_failure_threshold` (when a document flips to
  `failing`), `error_rate_threshold` (share of documents failing in one run
  that flags `run_error_rate`), `schema_failure_threshold`.
- **`retention`** — `log_days` (how long archives stay in `logs/` before
  `steward/history.py:prune` deletes them), `run_log_days` (same, for
  `runs.jsonl`).
- **`news`** — `enabled`, `window_days` (how long items stay in
  `news/feed.json`), `min_relevance` (items scoring below it are not kept),
  `max_new_items_per_source`, `enrich` / `enrich_batch_size` /
  `max_enrich_items` (the model pass), `exclude_title_patterns` (regexes for
  live blogs, podcasts and similar, validated at startup), and the vocabulary
  lists `ai_terms`, `australia_terms`, `government_terms`, `policy_terms`,
  `risk_terms` used by the AI gate and the keyword scorer.
- **`transparency`** — `enabled`, `register_url` / `register_selector`,
  `min_statements` and `keep_ratio` (the plausibility floor for a register
  read), `fetch_timeout_seconds` (plain-HTTP wait per agency site),
  `summarise` / `summary_batch_size` / `max_diff_chars` (the model pass),
  `event_days`.

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

`health.json` also carries `activity`: per-set counts over the last 30 days
of checks, would-be changes set aside (`cosmetic` + `reverted`), captures
rejected, and changes analysed / judged material, built from `runs.jsonl` by
`runlog.activity_summary`. The dashboard's Sources page and each policy page
show it, so the filtering is visible rather than taken on trust. Alongside it,
`activity_daily` (`runlog.daily_summary`) holds the same counts per set per
calendar day, which the dashboard draws as a status-page strip for each
source — a day read cleanly, a day with a rejected capture, a day with a
change.

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

`tests/test_pipeline.py`, `tests/test_run.py`, `tests/test_filtering.py`,
`tests/test_news.py`, `tests/test_fetching.py` and `tests/test_transparency.py`
are stdlib `unittest`, need no network, browser, or
`GEMINI_API_KEY`, and run in CI before `main.py` is even invoked.
`test_filtering.py` pins the September 2026 false changes (the charset
flip-flop, em-dash spacing, a link gaining `https://`, the poisoned
digital.gov.au baseline, a 503 spent as a schema retry); `test_news.py` pins
the news gates and the model contract; `test_fetching.py` pins the
blocked-host memory, the shared browser and the archive fallback's
newer-than-held rule; `test_transparency.py` pins the register parser against
five page layouts, the guard that stops a short read removing agencies, and a
statement change reaching the model alone. They're not a coverage exercise — several pin a specific
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
   - A policy set is for terms, guidance and policy that bind the reader.
     What other agencies publish about themselves — AI transparency
     statements — is its own stream (see
     [AI transparency statements](#ai-transparency-statements)), not a set.
   - `keywords` (optional) — names that identify this provider or agency in
     the news (`["Anthropic", "Claude"]`). A news item or incident matching
     one is linked to the set and listed on its page. All-caps terms match
     case-sensitively as whole words, so `ISM` does not match "tourism".
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

## News and AI incidents

The policy monitor answers "did a document I rely on change?". The news
pipeline (`news_watch.py`) answers the question after it: "what else happened
that I should know about?". It follows the same discipline — deterministic
gates first, one batched model call last, the orchestrator the only thing
that writes files — and runs as its own step after the policy check.

### Sources (`news_sources.json`)

Each entry is one feed:

```json
{
  "id": "the-mandarin",
  "name": "The Mandarin",
  "publisher": "The Mandarin",
  "category": "Australian news",
  "kind": "news",
  "type": "rss",
  "url": "https://www.themandarin.com.au/feed/",
  "homepage": "https://www.themandarin.com.au/",
  "note": "Shown on the Sources page."
}
```

- `id` — lower-case letters, digits and hyphens; the key in `news/state.json`.
- `name` — the feed's name on the Sources page; `publisher` (optional) — the
  outlet as readers know it, shown on each story ("ABC News" for the feed
  "ABC News — AI"). Google News items carry their own publisher.
- `category` — the News page's filter: `Australian Government`,
  `Australian news`, `Analysis`, `International`, `AI providers` (incident
  sources use `AI incidents`).
- `kind` — `news` or `incident`.
- `type` — `rss` (RSS 2.0, RSS 1.0 and Atom) or `oecd_aim`.
- `ai_focused` (optional) — the feed is about AI by construction (the ABC's
  AI topic, an AI lab's blog, a search for "artificial intelligence"), so its
  items skip the AI gate. Leave it off for general feeds: their items are
  only admitted when the *headline* mentions AI.
- `paywalled` (optional) — stories are marked "Subscriber" on the dashboard.
- `relevance_floor` (optional, 0–3) — lift every AI item from this source to
  at least this score (the UK AI Security Institute publishes nothing that is
  merely "general AI news").
- `via` (optional) — shown as "via …" (used for Google News searches).

Many `gov.au` sites (DTA, digital.gov.au, cyber.gov.au, industry.gov.au,
eSafety) refuse automated feed readers from datacentre addresses, including
GitHub's runners. They are reached through Google News searches restricted to
`site:gov.au`, whose headlines must mention AI to be kept.

The Guardian needs no API key: its tag pages have RSS, and a "combiner" URL
intersects two tags — `australia-news+technology/artificialintelligenceai/rss`
is Guardian Australia's AI coverage. The ABC's topic feeds are addressed by
the topic's numeric id (`/news/feed/13876586/rss.xml` is the AI topic; the id
is in the topic page's source as its `coremedia://channel/…` uri).

Feeds in the shipped list, by category: **Australian Government** — `gov.au`
pages via Google News, the Prime Minister's media releases; **Australian
news** — ABC News (AI topic), Guardian Australia (AI), SBS News, The Canberra
Times (paywalled), The Mandarin, Government News, iTnews, and two Google News
searches (APS and government AI coverage; AI regulation); **Analysis** — The
Conversation (AI topic), the OECD.AI blog; **International** — the UK AI
Security Institute and DSIT, the European Commission; **AI providers** — a
Google News search for coverage of provider terms, privacy and data-retention
changes, OpenAI, Google and Microsoft; **AI incidents** — three OECD AIM
slices.

An `oecd_aim` source carries a `query` for the [OECD AI Incidents
Monitor](https://oecd.ai/en/incidents) search API (the endpoint oecd.ai's own
incident browser posts to):

```json
"query": {
  "countries": ["AUS"],
  "industries": ["Government, security, and defence"],
  "order_by": "date | n_articles | score",
  "lookback_days": 45,
  "num_results": 100,
  "min_articles": 1
}
```

AIM records several hundred incidents a month, and the API returns at most
100 per request, so the shipped config asks for three slices: every incident
located in Australia, the most-reported government-sector incidents worldwide
over a fortnight, and the handful reported most widely overall.

### Gates (`steward/news.py`)

1. **Window** — entries published before `news.window_days` are ignored, not
   ingested and archived (OpenAI's feed alone carries 1,200 items).
2. **Identity** — an item's id is a hash of its canonical URL (tracking
   parameters, fragments and `www.` removed); ids already held or seen
   (`news/state.json`) are skipped, so each item is scored once.
3. **Format gate** — headlines matching `news.exclude_title_patterns` (live
   blogs, podcasts, cartoons, newsletter round-ups) are dropped; the same news
   arrives as a proper article. Publisher furniture at the end of an excerpt
   (WordPress's "The post … appeared first on", the Guardian's "Continue
   reading…" and newsletter plugs) is stripped too.
4. **AI gate** — see `ai_focused` above; `news.ai_terms` is the vocabulary,
   matched against the headline of a general feed's items. An excerpt-only
   mention — a press-conference transcript that touched on AI — is noise for
   the reader and tokens for the model. All-caps terms (`AI`, `DTA`, `ISM`)
   match case-sensitively as whole words, so "said" is not about AI and
   "tourism" does not mention the ISM.
5. **Keyword relevance** — a 0–3 score and reason from `australia_terms`,
   `government_terms`, `policy_terms` and `risk_terms`, on the same rubric the
   model gets (3 highly relevant, 2 directly relevant, 1 worth knowing, 0 skip).
6. **Cross-links** — an item matching a policy set's optional `keywords` in
   `policy_sets.json` is linked to it and appears on that policy's page.
7. **One story, one item** — near-identical headlines fold together, against
   stories already held as well as within the run, *before* the model is
   called, so it is never paid to read a story twice. The outlet's own copy
   (a direct link and an excerpt) takes the lead over a Google News copy of
   the same headline unless that copy has already been enriched. The model
   folds the rest (below). Other outlets are kept on the lead item as
   `coverage`.

The gates are also the cost control. Measured over the week to 24 September
2026 (an unusually heavy one), the 24 shipped feeds yield about 30 new items
a day after gating — about 8 of them from the ABC, Guardian, SBS, Canberra
Times, Government News, Conversation and provider-policy feeds added that
day — at roughly 70 tokens of item text each, with 19 repeats a week folded
before the model.

Items keep a headline, link, a ≤320-character publisher excerpt with markup
and images stripped, and our own TLDR — never the article body.

### Enrichment (`steward/news_enrichment.py`)

New items, plus any held item still on a keyword score (the model was down
last time), are sent most-promising-first in batches of
`news.enrich_batch_size`, at most `news.max_enrich_items` per run. The model
returns, per item: a ≤30-word `tldr` using only what the item says (empty if
it is only a headline), a 0–3 `relevance`, a short `reason`, `topics` from a
fixed list, and `same_story_as` — the id of an earlier story (it is shown the
last ten days of headlines) or another item in the batch reporting the same
event. A `response_schema` constrains the reply; `parse_and_validate` drops
unknown ids, out-of-range scores and links to stories it was not shown. One
retry per batch; a failed batch leaves its items on their keyword scores.
Feed text is fenced and labelled as untrusted data in the prompt, and the
TLDR is rendered as plain text.

Items the model scores below `news.min_relevance` leave the feed.

### Health

Each feed's `consecutive_failures`, `last_success` and `last_error` are kept
in `news/state.json` and summarised into `news/feed.json`'s `sources` block
with the same ok / degraded / failing thresholds as policy sources; the
Sources page shows them. Feeds do not raise `source-health` issues — a news
feed being down is visible on the dashboard, but it is not the silent false
negative the policy alerting exists to catch.

### Adding a feed

1. Find an RSS/Atom URL (or decide on an AIM query) and add an entry to
   `news_sources.json`.
2. `python news_watch.py --dry-run --only your-feed-id` — check the entry
   count, what was dropped and why, and the scores of the first items.
3. Commit; the next scheduled run ingests and enriches it.

## AI transparency statements

`transparency_watch.py` keeps the dashboard's third stream: what Commonwealth
agencies say about their own use of AI. It is neither a policy that binds the
reader nor an incident, so it has its own tab, stays out of the review queue,
and appears on the overview as "Across government".

    register -> links -> each statement through the policy gates
             -> one batched model call for the statements that changed

1. **The register** (`transparency.register_url`, the DTA's central register)
   is fetched like any document, but read for its **links**:
   `steward/transparency.py:parse_register` walks the page once, tracking the
   "Mandatory statements" / "Voluntary statements" section and the portfolio
   (from headings, accordion controls, bold labels, nested lists or a table's
   portfolio column), and takes each link that is an entry — a list item or
   table cell, or a paragraph that is nothing but links — as one agency's
   statement. Links in explanatory prose are not agencies. Each statement's
   id is its agency name slugged, so a statement moving address is
   `relinked`, not removed and added.
2. **Plausibility**: a register read with fewer than `min_statements` links,
   or fewer than `keep_ratio` of the list already held, is rejected — a block
   page or a redesign must never read as most of the Commonwealth
   withdrawing. The held list is kept and every statement is still checked.
3. **Register events** are worked out by comparing the two lists
   (`added`, `removed`, `relinked`) — no model call. The first read is a
   baseline and records no events.
4. **Each statement** goes through `main.process_document` — the same probe,
   validation, normalisation, revert check, diff and cosmetic gate as a
   policy document — with its baseline in `transparency/snapshots/`. Plain
   GETs use the shorter `fetch_timeout_seconds` and one attempt; the run's
   `FetchSession` sends agency hosts that refuse plain HTTP straight to the
   browser. A statement published as PDF is read with `pypdf`.
5. **The model** sees only statements that genuinely changed, batched
   (`summary_batch_size` per call), each as agency name plus diff, fenced as
   untrusted data. It returns `material_change` (use cases, tools, public
   interaction, governance or the accountable official changed) or
   `no_material_change` (dates, contacts, wording), and a summary of at most
   35 words. Returned ids must be ones that were sent. A change it could not
   summarise is not stored, so it is retried next run. Events are `updated`
   or `reworded` accordingly; the dashboard hides `reworded` by default.
6. **Statement dates**: `statement_date` takes the latest date on a line that
   says what it is ("last updated", "reviewed", "published", "effective"…)
   or the line after one, ignoring future dates. The dashboard flags a
   statement dated more than a year ago as a prompt to look, not a finding.

```bash
python transparency_watch.py --dry-run          # read the register and every statement; write nothing
python transparency_watch.py --only ip-australia # one statement (the register is always read)
python transparency_watch.py --no-summary       # changes wait for the next run
```

`main.py` runs it after the policies unless `--skip-transparency` (or
`--only`) is given.

The register's markup was not captured when the parser was written:
digital.gov.au refuses non-browser clients, and the stored snapshot kept its
text but not its links. If the first run logs `register read rejected`, run
the dry run above and adjust `parse_register` against the real page;
nothing is lost meanwhile.

## Automation (GitHub Actions)

`.github/workflows/update_checker.yml` runs daily at 00:00 UTC (also on
manual dispatch, and on pushes to `main` touching frontend/config files). In
order: install deps → run the pipeline tests → install Chrome (for the
Selenium fallback) → run `main.py --skip-news --skip-transparency` → run
`transparency_watch.py` → run `news_watch.py` (each `continue-on-error`, so
one failing never stops the others' output being committed) → commit and
push any changed data files (including `news/` and `transparency/`) →
open/update a `source-health` issue if `health_alert.md` exists → build the
React app → copy the data files into `build/` (only archived *analyses*, not
archived *snapshots*, ship to `build/logs/`; `news/state.json` and
`transparency/snapshots/` are not shipped) → deploy to GitHub Pages →
finally, fail the job if any pipeline step exited non-zero, so a failure is
still red without holding back the deploy.

Run locally, `python main.py` does all three in turn; `--skip-news` and
`--skip-transparency` leave those streams out, and `--only` implies both.

`.github/workflows/generate_lockfile.yml` is a manual-dispatch-only helper
that regenerates `package-lock.json`.
