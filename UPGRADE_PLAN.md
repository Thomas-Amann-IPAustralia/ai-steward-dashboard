# AI Steward Dashboard — Upgrade Plan

**Date:** 13 August 2026
**Context:** Informed by the Tripwire System Plan and High Level Design, adapted for a 1:1 change monitor.

---

## 1. Why now: the dashboard is currently reporting things that did not happen

Three consecutive runs in August, all still in `logs/`, show the failure mode end to end.

| Date | What the scraper captured | What the dashboard told the steward |
|---|---|---|
| 7 Aug | ToS 56,982 b · Privacy 33,643 b · AUP 6,596 b | Change detected → LLM call → *"There are no changes between the provided old and new policy documents."* Priority `low`. |
| 8 Aug | ToS **354 b** · Privacy 33,643 b (identical) · AUP 6,596 b (identical) | **CRITICAL** — *"Perplexity AI has removed its comprehensive Terms of Service document."* |
| 9 Aug | ToS restored | **CRITICAL** — *"Perplexity AI has launched a comprehensive Terms of Service document, replacing a previously inaccessible page."* |

Perplexity did not delete and reinstate its Terms of Service. One URL failed to render, returned 354 bytes, passed the `FAILURE_SIGNATURES` check, and was accepted as legitimate content. Two false critical alerts followed, and the second one is the state the live dashboard is showing right now.

This is not an isolated case. Across the 255 archived analyses in `logs/`:

- **Perplexity alone has 129 recorded "changes"** — roughly one every three days for a year — of which **38 are rated critical**.
- **49 of 255 analyses (19%) are critical.** A badge that fires on a fifth of all observations is not a priority signal.
- At least one archived analysis carries priority `unknown`, which is not a value the prompt permits.

And a smaller bug that undermines the rest: the current Perplexity analysis is stamped `"date_time": "2024-05-16T10:00:00Z"`. The prompt asks the *model* for the current timestamp (`main.py:236-263`), so it invents one; `PolicyDetail.js:59` renders it faithfully. `formatDate` has no `NaN` guard to catch it (`constants.js:14-28`).

The tool's core promise is "we will tell you when something important changed." Every false critical spends that credibility. Everything below is ordered by how much of it each change buys back.

---

## 2. What to take from Tripwire, and what to leave

The instinct to borrow from Tripwire is right, but only the front half transfers. Tripwire's expensive machinery exists to answer *"which of 139 IPFR pages does this change affect?"* — a question the Steward Dashboard does not have. Its target is a reader, not a corpus. Adopting the relevance-scoring stack here would be building a search engine to find a document you are already holding.

### Worth taking

| Tripwire element | Why it applies here |
|---|---|
| Stage 1 — Metadata probe (ETag / Last-Modified) | Most days nothing changed. Don't launch a browser to find that out. |
| Stage 2 — Normalise → hash → word diff → cosmetic gate | Kills the noise that produced 129 Perplexity "changes". |
| Stage 2 — Significance fingerprint | Useful as *context for the LLM*, never as a veto. Regex-only version; skip spaCy. |
| Stage 3 — Diff generation | The diff is both the cheaper LLM input and the artefact the UI needs. |
| §6.2 — Content validation | Directly prevents the 8 Aug false critical. |
| §6.6 / §6.7 — Health alerting and run logging | Currently a broken source is invisible for months. |
| §7 — Single validated config file | Thresholds you'll want to tune without editing code. |
| §7.3 — Gmail IMAP ingestion | A proven pattern for getting email into a repo with no server. This is the newsletter feature. |
| §3.8 — Schema validation, retry once, permit "uncertain" | The model must be allowed to say *nothing material changed*. |

### Worth leaving

| Tripwire element | Why it doesn't apply |
|---|---|
| Stage 4 — YAKE + BM25 + weighted RRF fusion | Ranks a corpus. There is no corpus to rank — the diff maps to exactly one policy set. |
| Stage 5 — Bi-encoder chunk matching | Same. ~400 MB model to find a document you already identified. |
| Stage 6 — Cross-encoder + graph propagation | Answers "what else is affected?" Nothing else is affected. |
| Stage 7 — Cross-source trigger aggregation | Meaningful when many sources hit one page. Here it's 1:1. |
| SQLite corpus + embeddings + quasi-graph | Flat JSON on GitHub Pages is the right scale, and keeps the zero-infrastructure property. |
| Observation mode | Replace with a simple `--dry-run` flag. |

**The shape that suits a 1:1 monitor** is six cheap gates before one expensive call:

```
probe → validate → normalise + hash → diff → cosmetic gate → fingerprint → LLM
```

Five files, not nine stages.

---

## 3. Suggestions

Effort: **S** ≈ under a day · **M** ≈ a few days · **L** ≈ a week or more.

### A. Correctness and trust

Do these first. Until they are done, every other improvement is polish on a tool that reports things that did not happen.

**A1 — Reject implausible scrapes before they become changes. (M)**
Adopt Tripwire §6.2. After extraction, check per URL: minimum length (~500 chars), the existing `FAILURE_SIGNATURES`, and a **size-delta guard** — if new content is below ~60% or above ~250% of the stored length for that URL, treat it as suspect. Do not overwrite the snapshot, do not call Gemini, record a `suspect_scrape` and surface it as a source-health warning. Tripwire uses 30%/300%; policy documents are stable enough to justify tighter bounds. Make them configurable. *This single change prevents both August false criticals.*

**A2 — Hash and diff per URL, not per policy set. (M)**
`main.py:381-396` concatenates every URL in a set into one blob with one MD5. Three consequences, all visible in the August incident: one URL failing looks like the whole set changed; the steward cannot tell *which* document moved; and the LLM diffs 97 KB when 300 bytes moved. Store a per-URL hash map in `hashes.json` and roll up to set level for display. This is the enabling change for A1, B4 and D2.

**A3 — Stamp the analysis timestamp in code. (S)**
Remove `date_time` from the prompt schema (`main.py:236-263`) and set it from `datetime.now(AEST_TZ)` at save time. The model does not know what time it is and currently guesses.

**A4 — Validate the model's JSON, retry once, and let it decline. (M)**
`main.py:289-292` silently fills missing keys with `'Unknown'` and never checks that `priority` is one of the four permitted values — which is how a `priority: unknown` analysis reached the archive. Adopt Tripwire §3.8: enum validation, one retry, log and skip on second failure. Then add a `no_material_change` verdict. The model already writes *"there are no changes between the provided documents"* and is then forced to pick a priority anyway; let it say so cleanly, and when it does, don't bump `last_amended` and don't badge the set.

**A5 — Make a broken source visible. (M)**
When every fetch fails, `main.py:389-393` copies the previous entry forward and the UI shows nothing unusual. A steward cannot distinguish *"stable since February"* from *"has not been successfully read since February"* — and the second is a silent false negative on exactly the risk this tool exists to cover. Add `status`, `consecutive_failures` and `last_success` per source, and render a warning state in the sidebar and on the home page. Highest trust-per-hour change in this document.

**A6 — Close the remaining live bugs from `BUG_REPORT.md`. (S)**
Still open and now load-bearing: BUG-01 (`main.py:427`, argument order), BUG-02 (`DashboardHome.js:78` and `Sidebar.js:128`, unguarded `urls[0]`), BUG-05 (`main.py:180`, empty string treated as content — a contributor to A1's failure mode), BUG-06 (`constants.js:14-28`, no `Invalid Date` check — why the 2024 timestamp renders unchallenged), BUG-09 (`DashboardHome.js:72`, Space key).

### B. The filtration funnel

**B1 — Probe before fetching. (M)**
Tripwire Stage 1. Conditional GET with `If-None-Match` / `If-Modified-Since`; a 304 ends the check — no browser, no hash, no diff. Store `etag` and `last_modified` per URL alongside the hashes from A2. Across ~20 URLs this turns a typical day into a few seconds of HTTP instead of twenty Chrome launches.

**B2 — `requests` + `trafilatura` by default; Selenium only when needed. (M)**
`main.py:314-351` launches headless Chrome for every URL, and on failure launches a second Chrome through the proxy — with 3–7 s of deliberate sleeps per page (`main.py:148-151`). Most monitored pages are static HTML. Fetch with `requests` first and extract with `trafilatura`; fall back to Selenium only for URLs flagged `"render": true` in `policy_sets.json`, mirroring Tripwire's `force_selenium`. Trafilatura's boilerplate removal also replaces the hand-maintained tag blacklist at `main.py:167-180`, which is a significant source of the nav-and-whitespace noise.

**B3 — Normalise before hashing. (S)**
Tripwire Stage 2 Pass 1. Collapse whitespace runs and `\xa0`, decode HTML entities, normalise Unicode to NFC, and strip a configurable per-source noise list (Perplexity's rotating *"We recently updated our consumer Privacy Notice"* banner is a live example). Hash the normalised text. The 7 Aug run — a paid call that returned "no changes" — dies at this gate.

**B4 — Compute the diff, and send only the diff. (M)**
Tripwire Stage 2 Pass 2 and Stage 3. Run `difflib.unified_diff` over the normalised text. Empty diff → cosmetic, stop, no LLM call, `last_amended` untouched. Non-empty → send the changed hunks plus a few lines of surrounding context, instead of two 50,000-character documents (`main.py:281-282`). Three wins at once: sharper analyses because the model is told where to look, roughly an order of magnitude fewer tokens, and it produces the artefact D1 needs. Persist to `diffs/{file_id}.diff`.

**B5 — A regex-only significance fingerprint. (S)**
Tripwire Stage 2 Pass 3, minus spaCy. Scan **changed lines only** for dollar amounts, dates, percentages, section references, modal verbs (*must / may / shall / will not*), and a steward keyword watchlist: *arbitration, class action, indemnify, training data, retention, sub-processor, jurisdiction, personal information, government, Australia*. Pass the tags to the LLM as context — never as a gate. Tripwire is explicit that the fingerprint informs but has no veto over genuine content changes; keep that property, and reuse the same list in C4.

### C. The newsletter feed

The mailbox idea is sound, and Tripwire §7.3 has already solved the hard part: getting email into a repo with nothing but a secret and standard-library Python.

**C1 — Ingest with the pattern Tripwire proved. (M)**
Dedicated Gmail account, IMAP enabled, app password stored as `NEWSLETTER_GMAIL_APP_PASSWORD`. A new `newsletter_ingestion.yml` running twice daily uses stdlib `imaplib` + `email` to fetch `UNSEEN`, dedupe on `Message-ID`, mark read, and commit. No webhooks, no DNS, no OAuth, no new dependencies.

**C2 — Identify newsletters by `List-Id`, not `From`. (S)**
Senders rotate ESP subdomains constantly; `List-Id` and `List-Unsubscribe` are stable. Keep an allowlist in `newsletters.yaml` mapping `List-Id` → display name and publisher. Anything unmatched lands in a quarantine bucket you promote or block from the UI — a public signup address collects marketing and spam within weeks, and you want that decision to be one line of config rather than an inbox rule.

**C3 — One LLM call per issue, returning an array of stories. (M)**
Prefer the `text/plain` MIME part; fall back to HTML → text via trafilatura. Ask for, per story: `headline`, `tldr` (≤ 40 words), `source_url`, `topics[]`, `aps_relevance` (0–3), `relevance_reason` (one clause). One call per issue rather than per story keeps the cost close to what the policy pipeline already spends.

**C4 — Score relevance with a rubric, not embeddings. (M)**
This is where the "keep the filtration simple" instinct pays off. A four-band rubric in the prompt beats a similarity threshold you would have to calibrate, and unlike a cosine score it explains itself to the reader:

- **3 — Act on it.** Commonwealth and state AI policy, DTA and digital.gov.au, ACSC/ASD and the ISM, National Archives, OAIC and the Privacy Act, APSC guidance, procurement rules, Senate inquiries.
- **2 — Directly relevant context.** Policy or terms changes at vendors APS staff actually use — especially any vendor already in `policy_sets.json` — AI regulation in comparable jurisdictions (EU AI Act, UK, NZ, Canada, Singapore), and public-sector AI deployments and their failures.
- **1 — Worth knowing.** Major model releases, capability or pricing shifts, notable incidents and research.
- **0 — Skip.** Funding rounds, consumer product marketing, commentary, crypto adjacency.

Default the feed to ≥ 2 with a toggle to reveal 1s. Optionally boost items that hit the B5 watchlist — same list, no extra machinery.

**C5 — Cross-link news to the policies you already monitor. (M)**
The one genuinely Tripwire-flavoured idea worth keeping, at 1:1 cost. If an item mentions a vendor in `policy_sets.json`, attach it to that policy's detail page as "Related news" and link back. A dictionary lookup on vendor names and domains — no vectors, no graph. This is what makes it a *steward's* feed rather than another aggregator: *"Anthropic's terms changed on 21 July, and here are the three newsletter items about it."*

**C6 — Store TLDRs and links, not article bodies. (S)**
Newsletter content is third-party copyright and this deploys to a public site. Keep extracted metadata, your own summary, and a link to the original. Strip tracking parameters from URLs at ingest and never render remote images — newsletter bodies are full of tracking pixels. Cheap to do once, awkward to retrofit.

**C7 — Treat newsletter text as untrusted input. (S)**
It is arbitrary text from the internet flowing into a prompt whose output is rendered as markdown in the dashboard. Fence it with explicit delimiters and state that the content inside is data, not instructions; validate that every returned `source_url` is `http(s)` before storing it; keep ReactMarkdown's default of not rendering raw HTML.

**C8 — Feed shape. (S)**
`news/feed.json` holds a rolling 30 days and is what the app fetches; `news/archive/YYYY-MM.json` holds the rest. Same flat-file discipline as everything else, so the site stays a static deploy. Don't publish the mailbox address in the repo or on the site — sign-ups only.

### D. User experience

**D1 — Make the diff the default detail view. (M)**
The `<pre>` dump of the entire snapshot (`PolicyDetail.js:70-73`) is the least useful element on the page; nobody reads 97 KB of terms of service. Once B4 exists, render the unified diff with added/removed highlighting, collapsed to changed hunks ± 3 lines, and demote the full snapshot to a disclosure. This was the top item on your own wish list — B4 was the missing prerequisite.

**D2 — Show which document in the set changed. (S)**
Follows directly from A2: *"Anthropic Legal Policies — Acceptable Use Policy changed. Consumer Terms and Privacy Policy unchanged."* Today the steward gets a set-level badge and has to go looking.

**D3 — Make the home page a briefing, not a stat wall. (M)**
`DashboardHome.js` shows four counters and a seven-day list. What a steward wants on Monday morning is: what changed since I last looked, why it matters, what needs action. Restructure as: (1) needs attention — critical and high changes, plus any failing source; (2) this week's changes with one-line summaries inline; (3) top news items at relevance ≥ 2; (4) a quiet confirmation of everything checked and unchanged. "All stable" is information too, and should look deliberate rather than empty.

**D4 — Fix the stale priority badge. (S)**
The sidebar badge shows the priority of the last change, whenever that was (`Sidebar.js:134-138`). Anthropic still wears CRITICAL from 21 July. Either date it — *"critical · 21 Jul"* — or fade it after about 30 days. As it stands it trains people to ignore the badge, which is the opposite of what a priority signal is for.

**D5 — Ship the history timeline; the data is already there. (M)**
511 archived files in `logs/` are copied into every build (`update_checker.yml:128`), but GitHub Pages serves no directory listing, so the app can never enumerate them. Generate a `history.json` index at the end of each run — per `file_id`: timestamp, priority, summary, paths. The timeline you have wanted becomes a rendering job over data you have been collecting for a year. Stop copying 14 MB of logs into the build at the same time; ship the index and fetch entries on demand.

**D6 — A "copy briefing" button. (S)**
One button that produces a markdown or plain-text digest of the last seven days: changes, priorities, one-line summaries, links, plus the top news items. Stewards forward things to their team; make that a click rather than a copy-paste job. More useful than PDF export and a fraction of the work.

**D7 — Drop the Google favicon calls. (S)**
`Sidebar.js:128` and `DashboardHome.js:78` request `google.com/s2/favicons` on every render. From a tool aimed at public servants this is a third-party request that may be blocked on agency networks — leaving broken icons — and it discloses the list of monitored sites to Google. Cache favicons into `public/` at build time, or use lettermark chips.

**D8 — Accessibility and responsive polish. (M)**
There is one `@media` query in the entire stylesheet (`App.css:723`); the sidebar-plus-content layout needs a real mobile pass, because this is a thing people check on a phone. Add the still-open Space-key handler (`DashboardHome.js:72`), visible `:focus-visible` styles, and `aria-live` on the loading and error regions.

**D9 — A lightweight feedback loop. (S)**
Tripwire's four mailto categories are the right idea but heavy for a single operator. Minimal version: 👍/👎 on each analysis, opening a prefilled GitHub issue. Even twenty judgements would tell you whether "critical" means anything — and with 49 criticals in 255 analyses, that is worth finding out.

### E. Operability and housekeeping

**E1 — One validated config file. (S)**
`steward_config.yaml`: model name, thresholds (size-delta bounds, minimum length, diff context lines), retention, the B5 watchlist, the C4 relevance bands, check cadence. Validate at startup and fail fast with a clear message, as Tripwire §7 does. Constants are currently spread through `main.py:24-46` and tuning any of them means a code change.

**E2 — A run log. (M)**
Tripwire §6.7. One JSON record per source per run: probe result, validation outcome, whether the hash changed, diff size, fingerprint tags, whether the LLM was called, token counts, duration, outcome. Append to `runs.jsonl`. Without it you cannot answer *"how often does Perplexity actually change?"* or *"what is this costing?"* — and both questions get sharper the moment the news feed starts making calls. It is also what makes A5 possible and what lets you calibrate A1's thresholds against real distributions rather than guesses.

**E3 — Health alerting. (S)**
Tripwire §6.6, and BUG-04. Any source failing three consecutive runs, an error rate above 30%, or repeated schema failures should produce one email — reusing the SMTP setup from C1 — or open a GitHub issue. Silent failure is the current default, and it is how a source rots unnoticed for months.

**E4 — Clean up the orphans. (S)**
Currently shipping to the live site: `snapshots/OpenAI_Terms_Policies.txt` and its analysis (no longer in `policy_sets.json`), four hash-named leftovers (`14dd1b7a…`, `3ce0ddf4…`, `9e0f8c5a…`, `e65e379b…`), `analysis/bash.txt`, and `snapshots/example_snapshot`. Log retention is nominally 365 days but nothing prunes repository history.

**E5 — Four tests that lock in the behaviour above. (S)**
Not a coverage push. Just: normalisation is idempotent; a cosmetic diff produces no LLM call; the size-delta guard rejects the 8 Aug Perplexity capture — use the archived file as the fixture, it is already in `logs/`; schema validation rejects an out-of-enum priority.

**E6 — Move off the legacy Gemini SDK. (S)**
`google-generativeai==0.8.3` is the deprecated package; `google-genai` is the current one. Worth doing while the prompt code is already open for A3 and A4.

---

## 4. Suggested order

Sequencing matters here, because several items unlock others.

1. **Stop the false alerts** — A1, A2, A3, A6. The dashboard stops reporting things that did not happen.
2. **Normalise and diff** — B2, B3, B4. Kills the remaining noise and produces the artefact the UI needs.
3. **Earn trust back** — A4, A5, E1, E2, E3. The tool becomes honest about its own state.
4. **Cash in on the UI** — D1, D2, D5, D3. This is where the work becomes visible to the reader.
5. **The news feed** — C1 through C8, as its own self-contained increment.
6. **Everything else** — B1, B5, D4, D6–D9, E4–E6.

Steps 1 and 2 are the ones that matter. They are perhaps two weeks of work, and they change the tool from one that cries wolf every third day into one whose alerts are worth reading — which is the precondition for anyone caring about the news feed at all.
