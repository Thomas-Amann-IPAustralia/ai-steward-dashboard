# Security and good-practice review: follow-up

Date: 25 September 2026 · Scope: `main` at `2e2ce41`, compared with the first
review ([`SECURITY_REVIEW.md`](SECURITY_REVIEW.md), taken at `bb46a03`).

Since that review, 37 source and documentation files have changed (+4,523 / −147
lines). The main additions are:

- a third stream that follows AI transparency statements
  (`transparency_watch.py`, `steward/transparency.py`)
- a reworked fetch layer (`steward/fetching.py`): hosts that refuse plain
  HTTP go straight to the browser, one browser is shared across the run, the
  Internet Archive is used as a fallback, and PDFs are read with `pypdf`
- sector filters and a Transparency page in the dashboard
- three more pipeline steps in the workflow

This follow-up re-checks the twelve original findings against the current
code, repository settings and dependencies. It also looks for new risks
introduced by those changes, and assesses the project against the practices
you would expect from an experienced team.

## Summary

**None of the twelve original findings has been fixed, and none of the Phase 1
configuration actions has been done.** `main` is still unprotected, the stale
branches are still there, and there is still no Dependabot, CODEOWNERS or
`SECURITY.md`.

**The most serious finding, #1, is now considerably worse.** At the first
review, Chrome rendered 2 of 19 monitored documents. Today it renders **107 of
191 documents every day** (30 of 75 policy documents and 77 of 116
transparency statements). It still runs with `--no-sandbox`, and it still runs
in the one job that holds the repository-write token, the Pages-deploy token
and the Gemini key. The 77 agency sites were not chosen by the maintainer. A
remote page (the DTA register) lists them.

The new code is written with the same care as the old. The transparency prompt
is fenced as untrusted data, the ids that come back are validated, summaries
are truncated and rendered as plain text, and statement URLs are scheme-checked.
File names are built from slugs, so a path cannot escape its directory. The
proxy secrets are not passed to the new step. The risk is in what the new
features *connect to*, not in how the Python is written.

On good practice, the code itself is well above average. Modules are small and
pure, docstrings explain *why*, the linter is clean, 236 tests pass, config is
validated fail-fast, and the docs are thorough. The gaps are all around the
code:

- nothing checks a pull request before it merges
- state files fail silently
- the orchestrators import each other
- the toolchain is past end-of-life
- `.gitignore` silently ignores the React `public/` folder

### Status of the original findings

| # | Finding | Then | Now |
|---|---|---|---|
| 1 | Over-privileged CI job runs untrusted content next to write/deploy credentials | High | **Open, exposure much larger**: Chrome renders 107 documents a day instead of 2, and one browser is shared across the run. New untrusted parser (`pypdf`). |
| 2 | `main` unprotected; automation writes the deployable branch | High | **Open.** `main` is `protected: false`. Five stale `claude/*` branches and `gh-pages` still exist. |
| 3 | Prompt injection in policy analysis; model Markdown rendered with images/links | Medium | **Open.** `analysis.py:119` is unchanged. `PolicyDetail.js:283` and `HistoryTimeline.js:79` are unchanged. The new transparency prompt *is* fenced, so the fix is already in the codebase, just not applied here. |
| 4 | Supply chain | Medium | **Open, with a new part.** Same pins. `npm audit`: 64 (3 critical, 29 high). `pip-audit`: `requests` 2.32.3 (2 advisories). **Node 20, used by the workflow, reached end-of-life in April 2026.** `pypdf==6.19.0` was added: pinned and clean. |
| 5 | No Content-Security-Policy | Medium | **Open.** `public/index.html` is unchanged. Note G6 below: new files in `public/` are git-ignored, which will trip up the fix. |
| 6 | Proxy credentials in Chrome argv; raw exception text published | Low | **Open, surface wider.** `fetching.py:519` is unchanged. Raw `str(exc)` now also flows into `transparency/statements.json`, which is deployed. The new archive path stores only the exception *type*, which is the right pattern. |
| 7 | Unbounded response bodies; partial XML entity check | Low | **Open, broadened.** PDFs are now read whole (`_is_pdf` touches `response.content`). There is still no size cap anywhere except the post-hoc feed check. |
| 8 | `generate_lockfile.yml` has no `permissions:` | Low | **Open.** It also still uses Node 18, which reached end-of-life in April 2025. |
| 9 | Config URLs rendered as `href` without scheme validation | Low | **Open** for `policy_sets.json` and `news_sources.json` `homepage`. The new register URLs *are* validated (`transparency.py:211`). |
| 10 | Untrusted text in the auto-raised issue body | Low | **Open.** `health.py:157` is unchanged. |
| 11 | Gemini API key hygiene | Low | **Open or unverified** (cloud settings aren't visible from the repo). Error text archived in June and July 2026 shows the key on the **free tier** then. See 11a below. |
| 12 | Redirects followed without re-validation | Info | **Open, raised to Low.** The set of URLs fetched is now chosen by a remote page. See N1. |

### New security findings

| # | Finding | Severity |
|---|---|---|
| N1 | The transparency register decides what the privileged job fetches | **Medium** |
| N2 | One bad statement stops the whole transparency run | **Low** |
| N3 | Internet Archive captures are trusted as the source's current text | **Low** |
| N4 | The fetch layer deliberately evades bot controls on government sites | **Decision for the owner** |

### Good-practice findings

| # | Finding | Priority |
|---|---|---|
| G1 | No CI on pull requests; most backend changes aren't tested until the next nightly run | **High** |
| G2 | Scrape, commit and deploy share one workflow and a cancelling concurrency group | Medium |
| G3 | State files fail silently to empty, and `hashes.json` is written non-atomically | Medium |
| G4 | Orchestrators import each other; helpers are duplicated three times | Medium |
| G5 | Toolchain past end-of-life or deprecated | Medium |
| G6 | `.gitignore` ignores `public/` and every `lib/` directory | Medium |
| G7 | 95 failed analyses are still published as medium-priority changes | Medium |
| G8 | Alerting has turned into noise | Low |
| G9 | Pipeline output committed to the code branch | Low |
| G10 | Linting and type-checking not enforced; loose repository hygiene | Low |

---

## Original findings: what changed

Only what is new since the first review is covered here. The original
descriptions and fixes in `SECURITY_REVIEW.md` still apply unchanged.

### 1. Over-privileged CI job: exposure is now much larger

The job is identical in shape. It has workflow-wide `contents: write`,
`pages: write`, `id-token: write` and `issues: write`, and `persist-credentials`
is still on by default. What runs inside it has changed:

- **Chrome is now a main route, not a fallback.** `FetchSession` sends every
  document on a host that once refused plain HTTP straight to the browser for
  seven days. Four Commonwealth hosts are on that list today. Of the 116
  transparency statements, 77 are read through Chrome. Stored state:
  `route: render` on 77 statements and 30 policy documents, against 2
  documents at the first review.
- **One browser is shared across the whole run** (`FetchSession.driver`). One
  process lifetime now spans more than 100 third-party origins, and
  `--no-sandbox` (`fetching.py:499`) removes the barrier between each
  renderer and the runner.
- **New untrusted parsers.** `pypdf` reads PDFs from agency sites and from the
  Internet Archive. BeautifulSoup parses the register page.
- **Positive:** the new transparency and news steps get only `GEMINI_API_KEY`,
  not the `PROXY_*` secrets. That is the right instinct, but it doesn't help
  while `GITHUB_TOKEN` sits in `.git/config` for every step.

**Next step:** unchanged. Split the workflow as in the first review's
appendix, and add `transparency/` to the publish-data allowlist. Given the
new volume, removing `--no-sandbox` should come first, before any of the
Phase 3 code work. It is a one-line change. The runner user is not root, and
Chrome installed from Google's `.deb` includes its setuid sandbox helper, so
the sandbox should work on GitHub-hosted Ubuntu. Verify with one
`workflow_dispatch` run. If Chrome then fails to start, fix the sandbox
rather than turning it off again.

### 4. Supply chain: new end-of-life runtime

Everything in the original table still applies. In addition:

- The workflow builds with **Node 20, which reached end-of-life on 30 April
  2026**. `generate_lockfile.yml` uses Node 18. Neither `package.json`
  (`engines`) nor an `.nvmrc` pins a version, so local and CI builds can
  differ. Move both workflows to Node 24 LTS and add `"engines": { "node":
  ">=24" }`.
- The actions (`checkout@v4`, `setup-node@v4`, `setup-python@v4`,
  `cache@v3`, `github-script@v7`, `configure-pages@v4`,
  `upload-pages-artifact@v3`, `deploy-pages@v4`) are pinned to mutable tags,
  and several run on runtimes GitHub is retiring. Move each to its current
  major and pin it by SHA in the same change.

### 6. Raw exception text published: now on the Pages site too

`transparency/statements.json` is copied into the Pages build. Every
statement's `document.last_error` comes from `f"{type(exc).__name__}: {exc}"`
(`fetching.py:315`, `:481`), so remote-controlled error text is now served
from the site itself, not just the repository. The `scrub_error()` fix from
the first review covers it. The archive path (`fetching.py:386`, `:407`)
already stores only the exception type, and that is the pattern to follow.

### 11a. The Gemini key appears to be on the free tier

`logs/*_analysis.json` files from June and July 2026 contain quota errors for
the metric `generate_content_free_tier_requests`. On the free tier, Google's
terms allow it to use prompts and responses to improve its products. The
paid tier doesn't. The prompts contain only public web text, so the
exposure is small. Still, an APS-facing tool should run on terms its owner
has consciously accepted.

**Next step:** confirm which tier the key is on today. If it is still the
free tier, move it to a billed project with a budget alert. That also
removes the 5-requests-per-minute limit behind several past "Analysis
failed" entries (see G7).

---

## New security findings

### N1. The transparency register decides what the privileged job fetches — Medium

`transparency_watch.py` reads the DTA's register and then fetches every link
it lists. `parse_register` checks only that each link is http(s)
(`transparency.py:211`). Whoever can change that page therefore decides
which URLs the privileged job visits. That includes a compromised agency
CMS, a bad edit, or a link that later points at a domain that has lapsed.
The job then:

- renders those URLs in Chrome without a sandbox (finding 1)
- reads them into memory without a size cap (finding 7)
- commits their text to the public repository (`transparency/snapshots/`)
- deploys their diffs to the public site (`transparency/diffs/`)

A link to `http://169.254.169.254/…`, `http://localhost:…` or an internal
hostname would be fetched too. Whatever came back would be published if it
passed the length checks.
GitHub-hosted runners have little to reach, so today this is mostly a
channel for exploit delivery and resource exhaustion, not data theft.

`register_is_plausible` guards only against too *few* links. Nothing limits
how many new statements one read can add, or which hosts they may be on. Two
current statements are already outside `gov.au` (`agrifutures.com.au`,
`csiro.au`). Both are legitimate, but they show the list is not
host-constrained.

**Fix:**
1. Add `transparency.allowed_host_suffixes` to `steward_config.yaml`
   (default `[".gov.au"]`) and `transparency.allowed_hosts` for named
   exceptions such as `agrifutures.com.au` and `www.csiro.au`. A register link
   outside both is recorded as an `unreviewed` event and shown on the page,
   but never fetched. Validate the new keys in `steward/config.py`.
2. Add `transparency.max_new_statements` (for example 20). A register read
   that adds more than this is treated as implausible, the same way a read
   that loses too many is.
3. In `fetching.py`, refuse any URL (initial or after redirects) whose host
   resolves to a private, loopback, link-local or reserved address. This
   also closes finding 12 for every stream.
4. Add tests in `tests/test_transparency.py`:
   - an off-list host produces an event but no fetch
   - a register that adds 200 links is rejected
   - a `169.254.169.254` link is refused

### N2. One bad statement stops the whole transparency run — Low

`transparency_watch.run` processes about 116 statements inside a single
`try/finally` (`transparency_watch.py:226–275`). It has no per-statement
`except`. Any exception raised while processing one document aborts the run,
and nothing is written: the register, the events and all the other
statements are lost for that day. `main.py` isolates each policy set
(`main.py:433`), and the code's own comment says "a scrape must not kill the
run". The new stream doesn't follow that rule.

`extract_pdf_text` makes this easy to trigger. It catches `(PdfReadError,
ValueError, KeyError, OSError)` (`fetching.py:263`), but several `pypdf`
errors are not subclasses of any of these: `ParseError`,
`LimitReachedError`, and the `PyPdfError` base class. PDFs are exactly
where malformed input turns up. An agency controls its own PDF, so one bad
file on one agency's site stops the stream for everyone until someone
intervenes.

**Fix:**
- Wrap each statement in `try/except Exception`. On failure, carry the prior
  entry forward with `status: fetch_failed` and a scrubbed error, and continue.
- In `extract_pdf_text`, catch `pypdf.errors.PyPdfError`.
- Read at most the first ~200 pages of a PDF.
- Add a test that makes one statement's fetch raise, and checks that the
  others are still processed and saved.

### N3. Internet Archive captures are trusted as the source's current text — Low

When every live route fails, `_archive_fetch` takes the newest Wayback
capture and treats it as the document's current text. That text is diffed,
can go to the model, and can badge a policy set. The safeguards are sound:
the capture must be newer than the last good read and at most 30 days old,
and it goes through the block-page and validation gates.

Two weaknesses remain:

- Anyone can ask the archive to capture any URL at any moment (Save Page
  Now). So the *timing* of a capture can be chosen by an outsider. For
  example, a capture could be triggered while a site serves a maintenance
  page, a geo-variant or a bot-variant that happens to pass validation.
- The archive's URL matching (http/https, `www`, trailing slash, redirects)
  can return a capture of a neighbouring URL. The code never checks the
  returned capture's `url`.

The route is shown in the document list (`PolicyDetail.js`). It is not
recorded in the change record, the analysis file or the timeline, so a
steward reading "critical: terms changed" can't tell the evidence was
second-hand.

**Fix:**
- Check that the capture's original URL matches the requested one after
  normalisation.
- Carry `route: archive` into `last_change`, the analysis file and
  `history.json`, and label it on the card.
- Consider holding an archive-only change at `analysis_pending` until a live
  read or a second capture confirms it, or at least never badging it above
  `medium`.

### N4. The fetch layer deliberately evades bot controls on government sites — decision for the owner

This is not a vulnerability. It is a governance question the code now
raises. The code's own comments describe four Commonwealth hosts
(`digital.gov.au`, `naa.gov.au`, `cyber.gov.au`,
`protectivesecurity.gov.au`) as running bot management that refuses plain
HTTP clients. There are also 77 agency hosts where a plain request failed
or timed out and Chrome then succeeded. The pipeline gets past these
controls in four ways:

- a spoofed desktop Chrome user agent
- `selenium-stealth` to hide automation markers
- `--disable-blink-features=AutomationControlled`
- an optional commercial proxy

The content is public, but those controls are other agencies' decisions.
This tool is published under an IP Australia staff account for APS readers,
so quietly circumventing them carries reputational and terms-of-use risk
that is worth deciding on deliberately.

**Suggested path:**
- Identify honestly, for example `User-Agent: AI-Steward-Dashboard/1.0
  (+https://github.com/Thomas-Amann-IPAustralia/ai-steward-dashboard)`.
- Honour `robots.txt`.
- Ask the DTA, ASD and NAA to allowlist the runner or offer a feed. The
  register in particular would be better as data than as scraped HTML.
- Keep the Internet Archive as the polite fallback.
- Drop `selenium-stealth` either way (finding 4).

---

## Good practice

### What is already good

It's worth saying clearly, because most projects of this size don't have
these:

- **Architecture.** Pure, independently testable modules in `steward/`, with
  thin orchestrators. The cost-control gates are explicit and documented.
- **Code quality.** `ruff` with pycodestyle, pyflakes and bugbear rules
  reports nothing. Docstrings explain *why* a thing exists, often with the
  incident that caused it.
- **Tests.** 158 Python tests and 78 frontend tests pass. They need no
  network, browser or API key. A real production capture is kept as a
  regression fixture. The production build succeeds with `CI=true`, so
  warnings would fail it.
- **Operational hygiene.** Config is validated fail-fast with helpful
  messages. There is a `--dry-run` mode, a structured run log with
  retention, per-source health, and a version stamp that forces a
  re-baseline when extraction changes.
- **Documentation.** `BACKEND.md` and `CLAUDE.md` are thorough and current.
- **Frontend discipline.** Hooks degrade gracefully when an optional file is
  missing, there's no `dangerouslySetInnerHTML`, and there are no
  third-party requests. Lettermarks replaced the Google favicon service for
  exactly that reason.

### G1. No CI on pull requests — High

The only workflow that runs tests is the nightly/deploy workflow on `main`,
and it runs after the merge. Its `push` path filter doesn't include
`steward/**`, `main.py`, `*_watch.py`, `tests/**`, `requirements.txt` or
`.github/**`. A backend change merged to `main` is therefore not tested at
all until the next midnight run. If it fails then, the tests fail *before*
the pipeline runs, so the dashboard silently stops updating. The six pull
requests merged on 24–25 September went in with no automated check.

**Fix:** add `.github/workflows/ci.yml`, triggered on `pull_request` (never
`pull_request_target`), with `permissions: contents: read` and
`persist-credentials: false`. It should run:

- `python -m unittest discover -s tests`
- `ruff check`
- `npm ci`, `npm test -- --watchAll=false`, `npm run build`
- `pip-audit -r requirements.txt`
- `npm audit --omit=dev --audit-level=high`

Make it a required status check in the `main` ruleset (finding 2).

### G2. Scrape, commit and deploy share one workflow and a cancelling concurrency group — Medium

A single `concurrency: pages` group with `cancel-in-progress: true`
(`update_checker.yml:28`) covers the scrape as well as the deploy. Since the
transparency stream was added, the scrape takes 20–30 minutes. Merging a pull request while the nightly run is in progress cancels
the run part-way through, and any model calls already made are paid for and
discarded. Every change under `src/` also re-runs the full scrape, even
though it only needs a rebuild. Eight steps repeat the same long `if:`
condition, a sign that they want to be a separate job.

**Fix:** this falls out of the finding 1 split:
- the collect job runs on `schedule` and `workflow_dispatch` only, in its
  own concurrency group with `cancel-in-progress: false`
- build and deploy run on `push` and after collect, keeping
  `cancel-in-progress: true`

### G3. State files fail silently to empty — Medium

`main.load_json_file` returns `{}` when `hashes.json` can't be parsed
(`main.py:92`). `save_json_file` writes in place (`main.py:103`). The news
and transparency orchestrators already use a temporary file and
`os.replace`, but `main.py` doesn't.

A truncated `hashes.json`, or one with merge-conflict markers left in it,
makes every policy set look new. That is realistic: the file is rewritten
daily by the bot, rebased in CI, and was hand-edited in `eec03d1`. When it
happens, each set gets an "Initial snapshot captured" analysis that
overwrites its real one, and any pending change is silently absorbed into
the new baseline.

**Fix:**
- Put one `load_state` / `save_state` pair in a small `steward/store.py`
  and use it from all three orchestrators. A missing file returns the
  default. An unparsable file stops the run with an error.
- Make all writes atomic.
- Add a step before the commit that checks every committed `*.json` parses.
- Add a test that a corrupt `hashes.json` aborts the run and does not
  re-baseline anything.

### G4. Orchestrators import each other — Medium

`transparency_watch.py` runs `import main` inside two functions (`:125`,
`:197`) to reach `process_document`, `fetch_route_fields`, `DOC_CHANGED` and
the private `_BASELINE_OUTCOMES`. Importing `main` also runs its
module-level `logging.basicConfig`. `main._run_streams` imports both
watchers in turn. `load_json`, `save_json`, `read_text` and `write_text` are
defined three times, and have already drifted apart (G3).

`mypy --ignore-missing-imports` reports 34 errors. Most are Optional
narrowing, but several come from one variable, `outcome`, holding a string
and then an `AnalysisOutcome` or `SummaryOutcome` in the same function. It
works, but it makes the functions harder to read.

**Fix:**
- Move `process_document`, the outcome constants and `fetch_route_fields`
  into `steward/monitor.py`. Pass the stored text in, so the module stays
  pure.
- Put file helpers in `steward/store.py` (G3).
- Move `logging.basicConfig` into `main()`.
- Rename the reused variables.
- `process_policy_set` is about 270 lines. Split it into
  fetch-all-documents, decide, and persist.
- Add `mypy` to CI in non-strict mode once the count is zero.

### G5. Toolchain past end-of-life or deprecated — Medium

- Node 20 (workflow) and Node 18 (lockfile workflow) are both past
  end-of-life (finding 4).
- Create React App (`react-scripts` 5.0.1) is deprecated. It sits in
  `dependencies`, so every `npm audit` reports 64 build-time advisories as
  if they shipped. That hides the moderate advisories that do
  ship, in `react-router`, `react-router-dom`, `@remix-run/router` and
  `mdast-util-to-hast`.
- Python dependencies have no lockfile, and `PyYAML` is a range.

**Fix:** Node 24 LTS plus `engines`; move `react-scripts` to
`devDependencies` now and plan the Vite migration (first review, 4.2);
`pip-compile --generate-hashes` to a `requirements.lock`.

### G6. `.gitignore` ignores `public/` and every `lib/` directory — Medium

`.gitignore:101` is `public`, a leftover from a Gatsby template. It matches
the React app's `public/` folder. The four files there are tracked only
because they were added before the rule or force-added. **Any new file in
`public/` is silently skipped by `git add`.** That includes the separate
theme script the CSP fix (finding 5) would need, a `robots.txt` or a
`404.html`.

`.gitignore:13` is `lib/`, which would likewise ignore a future `src/lib/`.

**Fix:** delete both lines, and prune the unrelated template sections
(Gatsby, Nuxt, Next, Parcel, Storybook). Confirm with `git check-ignore
--no-index -v public/x.js`.

### G7. 95 failed analyses are still published as medium-priority changes — Medium

Commit `eec03d1` removed two current badges that came from a stored Gemini
API error. The same defect remains in history: **95 entries in
`history.json`** (October 2025 to July 2026, 57 of them for Perplexity) have
the summary "Analysis failed." and priority `medium`. The analysis text is
raw API error text, mostly free-tier quota messages. The workflow copies
`logs/*_analysis.json` into the Pages build, so the timeline and charts
count them as real medium-priority changes.

**Fix:** in `history.build_index`, skip any archived analysis whose
`summary` is "Analysis failed." or whose `analysis` starts with "API
error:". Add a test so this can't recur. The files can then be left as
they are, or removed in one commit (`CLAUDE.md` allows fixing a specific
corrupted entry).

### G8. Alerting has turned into noise — Low

Issue #6, opened on 13 August 2026, has 45 comments: one for every degraded
run. It has never been closed. Nobody reads the 46th comment of an issue
like that. Transparency register failures raise no alert at all, only a red
run. The workflow also stamps "Generated by Claude Code" on the pipeline's
own issues (`update_checker.yml:145`). That is inaccurate, because the
steward workflow generated them.

**Fix:**
- Edit a single status comment instead of adding one per run.
- Close the issue automatically when health returns to `ok`.
- Comment only when the set of failing sources changes.
- Include the register's health in the alert.
- Change the footer to "Generated by the steward workflow".
- Fix finding 10 in the same change.

### G9. Pipeline output committed to the code branch — Low

44 of the last 62 commits are bot data commits. `logs/` holds 385 files
(12 MB). Code history, `git blame` and `git bisect` are cluttered, and every
pull request that touches `hashes.json` risks a conflict with the nightly
commit. Retention is enforced, which is good, but the underlying fix is the
same as first-review item 4.1: move pipeline output to a `data` branch.

### G10. Linting and type-checking not enforced; loose repository hygiene — Low

- The Python code is lint-clean today, but nothing keeps it that way. Add a
  `pyproject.toml` with `ruff` (and optionally `ruff format`) config, and
  run it in CI (G1).
- Planning documents accumulate at the root: `BUG_REPORT.md`,
  `UPGRADE_PLAN.md`, `THINGS I WANT TO IMPROVE.md` (the name contains
  spaces), and the reviews. Move them under `docs/`, for example
  `docs/reviews/` and `docs/archive/`. Turn the open items into GitHub
  issues, so the backlog has one home.
- Add the standard repository files: `SECURITY.md` (first review, 4.4),
  `.github/CODEOWNERS` (first review, finding 2) and
  `.github/dependabot.yml` (finding 4).

---

## What should happen next

This replaces the first review's action plan, re-ordered for what has
changed. Items 1–6 are settings changes with no code risk and take about an
hour. Items 7–15 are small independent pull requests, each with a test.
Items 16–19 are the structural work.

### Now: settings only

| # | Action | Addresses |
|---|---|---|
| 1 | Add a ruleset on `main`: require a pull request, block force-push and deletion. Add "require status checks" once item 7 lands | 2, G1 |
| 2 | Settings → Actions → General: set the default token to **read-only**; require approval for outside collaborators | 1, 2, 8 |
| 3 | Delete the five stale `claude/*` branches. Delete `gh-pages` if Settings → Pages shows the source as "GitHub Actions" | 2 |
| 4 | Gemini key: confirm the tier, move to billed if needed, restrict to the Generative Language API, add a budget alert | 11, 11a |
| 5 | Confirm secret scanning and push protection are on | — |
| 6 | Decide N4: honest identification, and ask agencies for access | N4 |

### Next two weeks: small pull requests

| # | Action | Addresses |
|---|---|---|
| 7 | Add `ci.yml` on `pull_request` (tests, ruff, frontend tests and build, audits) | G1 |
| 8 | Drop `--no-sandbox` from `initialize_driver` | 1 |
| 9 | Fix `.gitignore` (`public`, `lib/`) | G6, unblocks 11 |
| 10 | Per-statement exception isolation; catch `PyPdfError`; cap PDF pages | N2 |
| 11 | Fence the policy diff; disallow `img` and neutralise links in both `ReactMarkdown` uses; add the CSP and referrer meta tags | 3, 5 |
| 12 | Transparency host allowlist, new-statement cap, private-address refusal after DNS and redirects | N1, 12 |
| 13 | Shared atomic `steward/store.py` that fails loudly on corrupt state | G3, G4 |
| 14 | `requests>=2.33`; Node 24 in both workflows plus `engines`; `npm ci` only; `react-scripts` to `devDependencies`; actions at current majors, pinned by SHA; `dependabot.yml`; `permissions:` on `generate_lockfile.yml` | 4, 8, G5 |
| 15 | Skip failed analyses in `history.build_index` | G7 |

### Next month: structural

| # | Action | Addresses |
|---|---|---|
| 16 | Split `update_checker.yml` into collect → publish-data → build → deploy (+ alert), as in the first review's appendix, adding `transparency/` to the publish allowlist and separate concurrency groups; then rotate `GEMINI_API_KEY` and the proxy credentials | 1, G2, 11 |
| 17 | Remove `webdriver-manager` and `selenium-stealth`; move proxy auth off argv; add `scrub_error()`; stream responses with size caps; use `defusedxml` | 1, 4, 6, 7 |
| 18 | Move `process_document` into `steward/monitor.py`; split `process_policy_set`; add `mypy` to CI | G4 |
| 19 | Redesign alerting: single comment, auto-close, register health; escape the issue body | G8, 10 |

### This quarter

| # | Action | Addresses |
|---|---|---|
| 20 | Move pipeline output to a `data` branch | 2, G9 |
| 21 | Migrate from Create React App to Vite | 4, G5 |
| 22 | Record provenance for archive-sourced changes; hold them for confirmation | N3 |
| 23 | Tidy root docs into `docs/`; add `SECURITY.md`, `CODEOWNERS` | G10 |

---

## How this review was done

- Read every file changed since `bb46a03`, and re-read the code each
  original finding cites to confirm it is unchanged.
- Checked repository settings through the GitHub API: branch protection,
  branches, visibility, open issues, recent workflow runs.
- Measured exposure from the committed pipeline state (`hashes.json`,
  `transparency/statements.json`, `history.json`) rather than estimating it.
- Ran the checks locally:

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | 158 passed |
| `npm test -- --watchAll=false` | 78 passed (11 suites) |
| `CI=true npm run build` | Succeeds |
| `pip-audit -r requirements.txt` | `requests` 2.32.3: PYSEC-2026-1872 (fixed 2.32.4), PYSEC-2026-2275 (fixed 2.33.0) |
| `npm audit --package-lock-only` | 64 (3 critical, 29 high, 18 moderate, 14 low); the same with `--omit=dev`, because `react-scripts` is a runtime dependency |
| `ruff check --select E,F,B,S` | Only S314 (`xml.etree`, finding 7), S110 and S311 |
| `mypy --ignore-missing-imports` | 34 errors in 7 files, mostly Optional narrowing and reused variables |
| `git check-ignore --no-index -v public/x.js` | `.gitignore:101:public` |
