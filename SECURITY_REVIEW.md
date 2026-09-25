# Security review — AI Steward Dashboard

Date: 25 September 2026 · Scope: the full repository at `bb46a03` (`main`)
covering the Python pipeline (`main.py`, `news_watch.py`, `steward/`), the
React dashboard (`src/`, `public/`), the GitHub Actions workflows, the
dependencies, and the repository settings visible through the GitHub API.

## Summary

The application code is careful. URLs are scheme-checked before fetching,
news links are canonicalised to http(s), YAML goes through `safe_load`, feeds
that declare entities are refused, the news prompt fences third-party text as
data and validates the ids that come back, and the frontend never uses
`dangerouslySetInnerHTML`. No secrets turned up in the 717-commit history.

The serious risk is in **how the pipeline runs**, not in the Python. One
GitHub Actions job does all of these at once:

- renders arbitrary third-party JavaScript in headless Chrome with
  `--no-sandbox`
- parses untrusted HTML and XML
- installs about 1,500 npm packages
- holds a repository-write token, a Pages-deploy token, an OIDC token, the
  Gemini key and the proxy credentials

The site is public, and `main` is unprotected. If anything in that job is
compromised, an attacker can change what the public dashboard serves. The
path is either a push to `main` or a direct Pages deploy.

| # | Finding | Severity |
|---|---|---|
| 1 | One over-privileged CI job runs untrusted content next to write/deploy credentials | **High** |
| 2 | `main` is unprotected and the deployable branch is written by automation | **High** (combined with 1) |
| 3 | Indirect prompt injection in policy analysis; model Markdown rendered with images and links | **Medium** |
| 4 | Supply chain: unpinned/unhashed deps, runtime driver download, `npm install` fallback, known advisories | **Medium** |
| 5 | No Content-Security-Policy on the public site | **Medium** |
| 6 | Proxy credentials on the Chrome command line; raw exception text published | **Low** |
| 7 | Unbounded response bodies and a partial XML entity check | **Low** |
| 8 | `generate_lockfile.yml` has no `permissions:` block | **Low** |
| 9 | Config URLs rendered as `href` without scheme validation | **Low** |
| 10 | Untrusted text in the auto-raised GitHub issue body | **Low** |
| 11 | Gemini API key hygiene | **Low** |
| 12 | Redirects followed without re-validation | **Info** |

---

## Findings

### 1. One over-privileged CI job runs untrusted content next to write/deploy credentials — High

`.github/workflows/update_checker.yml` has a single job, `check-and-build`,
with workflow-wide `permissions: contents: write, pages: write, id-token:
write, issues: write` (line 20). Inside that job:

- `actions/checkout@v4` runs with the default `persist-credentials: true`. The
  `GITHUB_TOKEN` is written into `.git/config`, where every later step and
  every process it spawns can read it.
- `main.py` fetches third-party pages. For `render: true` URLs, and as a
  fallback for any plain fetch that fails, it launches headless Chrome with
  `--no-sandbox` (`steward/fetching.py:272`) and runs the page's JavaScript.
  With the sandbox off, a single renderer bug in Chrome gives the page code
  execution on the runner.
- `pip install` and `npm ci || npm install` run install scripts from hundreds
  of transitive packages.
- `GEMINI_API_KEY` and all four `PROXY_*` secrets are in the environment of
  the scraping step.

**Impact.** A malicious or compromised monitored page, or a malicious
dependency, can read the token and push to `main` (see finding 2). It can
also publish a Pages artifact directly, or mint an OIDC token. Either way,
arbitrary JavaScript ends up on
`thomas-amann-ipaustralia.github.io/ai-steward-dashboard`, which is a public
site presented as a resource for Australian Public Servants. The same access
exfiltrates the Gemini key and the proxy credentials, and lets the attacker
open or edit issues.

The job has no pull-request trigger, so the classic "pwn request" attack
does not apply. The exposure is to content and dependencies, not to
outside contributors.

**Fix.** Split the workflow into jobs with least privilege, and pass data
between them as artifacts. A skeleton is in the appendix.

1. **collect** (`contents: read`, `persist-credentials: false`). Runs tests,
   `main.py` and `news_watch.py`, and uploads the output directories as an
   artifact. This is the only job with `GEMINI_API_KEY` and the `PROXY_*`
   secrets, and it has no write token.
2. **publish-data** (`contents: write`). Downloads the artifact and checks it:
   only the expected paths (`hashes.json`, `health.json`, `history.json`,
   `runs.jsonl`, `analysis/`, `diffs/`, `snapshots/`, `logs/`, `news/`), valid
   JSON, and no files under `src/`, `public/`, `.github/` or `package*.json`.
   It then commits and pushes. It runs no third-party code.
3. **build** (`contents: read`). Runs `npm ci` only, with no fallback. Tests,
   builds, and runs `upload-pages-artifact`.
4. **deploy** (`pages: write`, `id-token: write`). Runs `deploy-pages` only.
5. **alert** (`issues: write`). Raises the health issue from a small artifact.

In addition:
- Keep Chrome's sandbox on. Drop `--no-sandbox` on the GitHub-hosted runner,
  where Chrome can sandbox, and add it back only if the job runs in a
  container that needs it. Better still, run the render step inside a
  throwaway container with no secrets mounted.
- Consider `step-security/harden-runner` in audit mode first, to see which
  network egress the collect job needs, and then restrict it.

### 2. `main` is unprotected and the deployable branch is written by automation — High (combined with 1)

The GitHub API reports `main` as `protected: false` and the repository as
public. The workflow pushes pipeline output straight to `main` (`git pull
--rebase && git push`). Because `src/**` pushes to `main` also trigger a build
and deploy, anything that can push to `main` can change the live site with no
review.

**Fix.**
- Add a branch ruleset on `main` that requires a pull request and blocks force
  pushes and deletions. Grant a bypass only to the `github-actions[bot]`
  integration, and only if you keep committing data to `main`.
- Better: move pipeline data to its own branch, such as `data`. The collect
  job writes there, and the build job checks out `main` for code and `data`
  for JSON. Then the automation token never needs write access to the branch
  that holds executable code.
- Add `.github/CODEOWNERS` covering `.github/`, `src/`, `public/`,
  `package*.json`, `requirements.txt`, `policy_sets.json`,
  `news_sources.json` and `steward_config.yaml`, and require code-owner review
  in the ruleset.
- Turn on "Require approval for all outside collaborators" for workflows, and
  confirm the repository's default workflow permission is **read-only**
  (Settings → Actions → General).
- Delete stale branches (`claude/*`, and `gh-pages` if Pages deploys from
  Actions).

### 3. Indirect prompt injection in policy analysis; model Markdown rendered with images and links — Medium

`steward/analysis.py` pastes the unified diff straight into the prompt after
`UNIFIED DIFF:` (line 119). Unlike the news prompt, it is not fenced as
untrusted data. The diff is built from third-party page text. Text planted on
a monitored page could therefore steer the model: an instruction to return
`no_material_change` would hide a real amendment, and a forced `critical`
would raise a false alarm. The schema limits the *shape* of the answer, but
not its *truth*.

The model's `analysis` field is then rendered as Markdown with
`<ReactMarkdown>` (`src/components/PolicyDetail.js:282`,
`src/components/HistoryTimeline.js:79`). `react-markdown` 9 blocks raw HTML
and `javascript:` URLs, so this is not XSS. It does render:

- `![](https://attacker.example/p.png)`: a remote image that every visitor's
  browser loads, which tracks visitors' IP addresses and user agents
- `[Re-verify your account](https://phish.example)`: a phishing link on a
  dashboard that looks authoritative

**Fix.**
- Fence the diff the same way `news_enrichment.PROMPT_TEMPLATE` fences news
  items, for example `<<<DIFF … DIFF>>>`, with an explicit instruction that
  the content is untrusted and any instructions inside it must be ignored.
- In both `ReactMarkdown` uses, pass `disallowedElements={['img', 'image']}`
  and a `components={{ a: SafeLink }}` that renders links as plain text, or
  allows only hosts in the set's own `urls`. Add `rel="noopener noreferrer
  nofollow"`.
- Add a unit test with a diff that contains an injection string and an image
  link. It should assert that the prompt fences the diff and that the
  rendered output contains no `<img>`.
- The CSP in finding 5 also stops the image beacon, as a second layer.

### 4. Supply chain — Medium

| Item | Where | Risk |
|---|---|---|
| Actions pinned to mutable tags (`@v4`, `@v3`, `@v7`) | both workflows | A moved tag runs new code with write/deploy tokens |
| `actions/setup-python@v4` and `actions/cache@v3` are deprecated | `update_checker.yml` | No security fixes |
| `npm ci \|\| npm install` | `update_checker.yml:164` | If `npm ci` fails, a fresh, unlocked resolution is built and deployed |
| Python deps pinned by version only, no hashes; `PyYAML>=6.0,<7`; transitive deps (e.g. of `google-genai`) unpinned | `requirements.txt` | A substituted or compromised package is installed silently |
| `webdriver-manager` downloads a chromedriver binary at run time | `steward/fetching.py:295` | An unverified binary runs in the privileged job |
| `selenium-stealth==1.0.6` | `requirements.txt` | Unmaintained since 2020 |
| `requests==2.32.3` | `requirements.txt` | pip-audit: PYSEC-2026-1872 (fixed in 2.32.4) and PYSEC-2026-2275 (fixed in 2.33.0) |
| `react-scripts` 5.0.1 (deprecated, unmaintained) | `package.json` | `npm audit`: 64 advisories (3 critical, 29 high), almost all build-time; it sits in `dependencies`, so none are filtered as dev-only |
| `react-router-dom` 6.30.3, `mdast-util-to-hast` 13.2.0 | runtime | Moderate advisories (open redirect; unsanitised `class`). Low exposure here (`HashRouter`, no user-controlled redirects), but should be patched |
| No Dependabot/Renovate config | `.github/` | Advisories are not surfaced |

**Fix.**
- Pin every action to a full commit SHA with a version comment. Move to
  `setup-python@v5` and `cache@v4`.
- Replace the fallback with a plain `npm ci`. A lockfile mismatch should fail
  the build.
- Generate `requirements.lock` with `pip-compile --generate-hashes` and
  install with `pip install --require-hashes -r requirements.lock`. Bump
  `requests` to at least 2.33.0.
- Remove `webdriver-manager`. Selenium 4.25 already includes Selenium Manager,
  and `google-chrome-stable` is installed by the workflow. Alternatively,
  install the matching `chromedriver` from the Chrome for Testing apt/JSON
  endpoint in the workflow and point `ChromeService` at it.
- Drop `selenium-stealth`, or replace it with a maintained option such as
  Playwright, which the repo could pin by version.
- Plan a move off Create React App to Vite. It is small for a static SPA like
  this one. Until then, move `react-scripts` to `devDependencies`, so audits
  reflect what actually ships.
- Add `.github/dependabot.yml` for `pip`, `npm` and `github-actions`, and add
  `pip-audit` and `npm audit --omit=dev --audit-level=high` steps to CI.

### 5. No Content-Security-Policy on the public site — Medium

GitHub Pages cannot set response headers, and `public/index.html` has no CSP
`<meta>`. The dashboard only ever needs its own origin, so a strict policy is
cheap. It would have stopped the tracking beacon in finding 3, and it limits
any future injection bug.

**Fix.** Add this to `public/index.html`:

```html
<meta http-equiv="Content-Security-Policy"
      content="default-src 'self'; script-src 'self' 'sha256-<hash of the inline theme script>';
               style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:;
               connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'">
```

The inline theme script in `index.html` needs its hash, or can be moved to
its own file. Also add `<meta name="referrer" content="strict-origin-when-cross-origin">`.
`frame-ancestors` cannot be set with a meta tag, so clickjacking protection
would need a host that serves headers, such as Cloudflare Pages. Low value
for a read-only site.

### 6. Proxy credentials on the Chrome command line; raw exception text published — Low

- `steward/fetching.py:292` passes
  `--proxy-server=http://user:pass@host:port` to Chrome. The password then
  shows in the process list and in any Chrome or driver crash log. Chrome
  also ignores credentials in `--proxy-server`, so the authenticated proxy
  path through the browser probably does not work at all.
- Exception text such as `f"{type(exc).__name__}: {exc}"` from `requests` and
  Selenium is stored as `last_error`. From there it goes into
  `hashes.json`, `health.json`, `runs.jsonl`, `news/state.json` and the
  auto-raised GitHub issue, all of which are public. GitHub masks secrets in
  logs but not in committed files. A proxy error can include the proxy host
  (`PROXY_HOST` is stored as a secret), and future library versions may
  include more. None of today's committed data leaks anything.

**Fix.**
- For the browser, use a local forwarding proxy, a Chrome extension or
  `selenium-wire` to supply proxy auth. Never put credentials in argv.
- Add a `scrub_error()` helper in `steward/fetching.py`. It should remove
  `user:pass@` from any URL, replace the values of `PROXY_HOST`, `PROXY_USER`
  and `PROXY_PASS` with `***`, and truncate to around 200 characters. Apply it
  wherever `error=` is set, and add a unit test.

### 7. Unbounded response bodies and a partial XML entity check — Low

- `fetching._http_fetch` and `feeds.fetch_rss` call `requests.get` without
  `stream=True`. `MAX_FEED_BYTES` is checked only after the whole body is in
  memory (`steward/feeds.py:259`), and policy pages have no cap at all. A
  hostile or broken endpoint can exhaust the runner's memory and fail the run.
- `parse_feed` refuses `<!ENTITY` only in the first 4 KB
  (`steward/feeds.py:168`). XML comments or processing instructions can push a
  DOCTYPE past that point. Python's bundled expat (2.4 and later) already
  limits entity amplification and never resolves external entities, so the
  practical risk is low. The check still gives false assurance.

**Fix.** Stream with `stream=True` and `iter_content`, and abort past a cap
(for example 8 MB for feeds and 5 MB for pages). Parse feeds with
`defusedxml.ElementTree.fromstring(body, forbid_dtd=True)`, which makes the
4 KB check unnecessary.

### 8. `generate_lockfile.yml` has no `permissions:` block — Low

Without an explicit block, the job inherits the repository default. On older
repositories that default is read/write for everything. The job runs
`npm install`, which executes install scripts, and then pushes.

**Fix.** Add `permissions: contents: write` and nothing else. Or delete the
workflow, since the lockfile is committed and Dependabot can maintain it.

### 9. Config URLs rendered as `href` without scheme validation — Low

`main.validate_policy_sets` (`main.py:165`) does not call `is_safe_url` on
`urls[].url`, and `news_watch.validate_sources` never checks `homepage`. Both
are rendered as `<a href>` (`PolicyDetail.js:159,327`, `SourcesView.js:239`).
Fetching is still protected, because `fetch_document` refuses unsafe URLs,
but a `javascript:` value would become a clickable link. React 18 only warns
about these. The files are maintainer-controlled, so this matters only if a
bad entry is merged.

**Fix.** Reject non-http(s) URLs in both validators. Add a `safeHref()` helper
in `src/utils/constants.js` that returns `undefined` unless the protocol is
`http:` or `https:`, and use it for every external `href`.

### 10. Untrusted text in the auto-raised GitHub issue body — Low

`health.render_alert_markdown` puts `url` and `detail` into a Markdown table.
`detail` can contain remote error text. Only `|` is escaped, so an `@name`
mention or a Markdown link in an error string would ping users or render as a
link in the issue.

**Fix.** Wrap `url` and `detail` in inline code spans (with backticks
escaped), or escape `@`, `[`, `]` and `<`.

### 11. Gemini API key hygiene — Low

The key is read from Actions secrets and never logged, which is good. There
is no evidence of these extra controls:

- In Google Cloud, restrict the key to the Generative Language API only.
- Set a quota or budget alert on the project.
- Rotate the key after the CI restructure in finding 1. Until then it has
  lived in a job exposed to third-party code.
- Make it an **environment** secret on a dedicated environment used only by
  the collect job, rather than a repository secret.

Model spend is already well bounded: one call per changed set, a 40,000
character diff cap, and a 120-item news cap.

### 12. Redirects followed without re-validation — Info

`requests` follows redirects (`allow_redirects=True`), and neither the
scheme check nor any host check is re-applied to the final URL. Since
`requests` only follows http(s), the risk is limited to a monitored site
redirecting the runner to an internal or link-local address, and the
response being published as a "snapshot". GitHub-hosted runners have little
to reach, and Azure IMDS requires a special header.

**Fix (optional).** After the fetch, check that `response.url` is http(s) and
that its host does not resolve to a private, loopback or link-local range.
Otherwise treat it as a failed fetch.

---

## What is already done well

- `is_safe_url` / `canonical_url` restrict fetched and rendered news URLs to
  http(s).
- `yaml.safe_load` is used, and the config is validated with fail-fast type
  checks.
- The news prompt is fenced and labelled as untrusted. Model output is
  validated against the ids that were sent, and TLDRs are rendered as plain
  text.
- React escaping is used throughout. There is no `dangerouslySetInnerHTML`,
  `react-markdown` blocks raw HTML, and external links carry
  `rel="noopener noreferrer"`.
- There are no `pull_request_target` or PR-triggered workflows.
- `news/state.json` is stripped from the Pages build. Archived snapshots are
  not shipped.
- No secrets were found in git history, and `.env` is gitignored.
- Model cost is capped, and feeds that declare entities are refused.

---

## Action plan

### Phase 1 — this week (configuration only, no code risk)

| # | Action | Addresses |
|---|---|---|
| 1.1 | Settings → Actions → General: default workflow permissions **read-only**; require approval for outside collaborators | 1, 2, 8 |
| 1.2 | Add a branch ruleset on `main`: require PR, block force-push and deletion, bypass for `github-actions[bot]` only | 2 |
| 1.3 | Restrict the Gemini key to the Generative Language API; add a budget alert | 11 |
| 1.4 | Confirm secret scanning and push protection are on (Settings → Code security) | — |
| 1.5 | Add `permissions: contents: write` to `generate_lockfile.yml`, or delete it | 8 |
| 1.6 | Delete stale `claude/*` branches | 2 |

### Phase 2 — next 2 weeks (CI hardening)

| # | Action | Addresses |
|---|---|---|
| 2.1 | Split `update_checker.yml` into collect → publish-data → build → deploy (+ alert) jobs with least privilege, `persist-credentials: false`, and an output-path allowlist in publish-data (see appendix) | 1 |
| 2.2 | Pin all actions to SHAs; upgrade `setup-python` and `cache`; add `dependabot.yml` for pip, npm and actions | 4 |
| 2.3 | Replace `npm ci \|\| npm install` with `npm ci` | 4 |
| 2.4 | Lock Python deps with hashes; bump `requests` to ≥ 2.33.0; add `pip-audit` and `npm audit --omit=dev` CI steps | 4 |
| 2.5 | Remove `webdriver-manager` (use Selenium Manager or a pinned chromedriver) and `--no-sandbox`; drop `selenium-stealth` | 1, 4 |
| 2.6 | Rotate `GEMINI_API_KEY` and proxy credentials once 2.1 is live; move them to a collect-only environment | 1, 11 |

### Phase 3 — next month (code changes, each with a test)

| # | Action | Addresses |
|---|---|---|
| 3.1 | Fence the diff as untrusted data in `analysis.PROMPT_TEMPLATE`; add an injection regression test | 3 |
| 3.2 | Disallow `img` and neutralise links in both `ReactMarkdown` uses | 3 |
| 3.3 | Add the CSP and referrer `<meta>` tags to `public/index.html` | 3, 5 |
| 3.4 | Add `scrub_error()` and apply it to every stored `error`; move browser proxy auth off argv | 6 |
| 3.5 | Stream responses with size caps; switch feed parsing to `defusedxml` | 7 |
| 3.6 | Validate URL schemes in `validate_policy_sets` / `validate_sources`; add a `safeHref()` in the frontend | 9 |
| 3.7 | Escape untrusted fields in `render_alert_markdown` | 10 |

### Phase 4 — next quarter (structural)

| # | Action | Addresses |
|---|---|---|
| 4.1 | Move pipeline output to a `data` branch so automation never writes to the code branch | 2 |
| 4.2 | Migrate the frontend from Create React App to Vite; clears most `npm audit` findings | 4 |
| 4.3 | Run the render fallback in a throwaway container with no secrets; restrict runner egress (`harden-runner`) | 1 |
| 4.4 | Add a `SECURITY.md` with a reporting contact | — |

---

## Appendix — least-privilege workflow skeleton

```yaml
permissions: {}            # nothing by default; each job asks for what it needs

jobs:
  collect:
    runs-on: ubuntu-latest
    permissions: { contents: read }
    environment: pipeline  # holds GEMINI_API_KEY and PROXY_* only
    steps:
      - uses: actions/checkout@<sha>  # v4
        with: { persist-credentials: false }
      - uses: actions/setup-python@<sha>  # v5
        with: { python-version: '3.11' }
      - run: pip install --require-hashes -r requirements.lock
      - run: python -m unittest discover -s tests -v
      - run: python main.py --skip-news
        continue-on-error: true
        env: { GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}, PROXY_HOST: ..., ... }
      - run: python news_watch.py
        continue-on-error: true
        env: { GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }} }
      - uses: actions/upload-artifact@<sha>
        with:
          name: pipeline-output
          path: |
            hashes.json
            health.json
            history.json
            runs.jsonl
            analysis/
            diffs/
            snapshots/
            logs/
            news/
            health_alert.md

  publish-data:
    needs: collect
    runs-on: ubuntu-latest
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@<sha>
      - uses: actions/download-artifact@<sha>
        with: { name: pipeline-output, path: out }
      - name: Validate and copy only expected paths
        run: |
          # refuse anything outside the allowlist, and check every *.json parses
          ...
      - run: git add ... && git commit ... && git push

  build:
    needs: publish-data
    runs-on: ubuntu-latest
    permissions: { contents: read }
    steps:
      - uses: actions/checkout@<sha>
        with: { persist-credentials: false, ref: main }
      - uses: actions/setup-node@<sha>
      - run: npm ci
      - run: npm test -- --watchAll=false
      - run: npm run build
      - run: ./scripts/copy-data.sh
      - uses: actions/upload-pages-artifact@<sha>
        with: { path: ./build }

  deploy:
    needs: build
    runs-on: ubuntu-latest
    permissions: { pages: write, id-token: write }
    environment: { name: github-pages, url: ${{ steps.d.outputs.page_url }} }
    steps:
      - id: d
        uses: actions/deploy-pages@<sha>

  alert:
    needs: collect
    runs-on: ubuntu-latest
    permissions: { issues: write }
    steps:
      - uses: actions/download-artifact@<sha>
        with: { name: pipeline-output }
      - uses: actions/github-script@<sha>
        # existing issue-raising script
```
