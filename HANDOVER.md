# Handover — review remediation, September 2026

**Branch:** `claude/repo-review-features-k3f74g`
**Written:** 16 September 2026 · **Updated:** 17 September 2026 (Week 1 complete)
**For:** whoever (human or agent) picks this up next.

Read [`REVIEW_2026-09.md`](REVIEW_2026-09.md) first — it is the analysis this
work comes from, and every section reference below points into it. This document
covers only what has actually been done, what deliberately has not, and what to
watch.

---

## 1. State of this branch

Four commits: the review, the Day-1 remediation (`REVIEW_2026-09.md` §9 items
1–4), a merge of the 17 September run from `main`, and Week 1 (§9 items 5–8).

```
Python tests   109 pass  (was 57; 52 added)
Frontend tests  16 pass  (was 11)
npm run build   compiles clean under CI=true (warnings are errors)
main.py         --dry-run verified against live sources and the disabled path
```

**Day 1 and Week 1 of `REVIEW_2026-09.md` §9 are both done.** The next
unstarted item is the news feed, RSS first (§6.1).

**Nothing here has run in CI yet.** The pipeline has not executed against the
repaired state on a GitHub runner. §5 lists what to check on the first real run.

---

## 2. What changed, and why

### 2.1 The dashboard was asserting things that were not true (§3.1)

Four of the eight files in `analysis/` carried dates the model invented before
`steward/analysis.py` stamped them in code. The worst was Perplexity: a
`critical` badge dated **16 May 2024** describing a change that never happened —
the 8–9 August 2026 capture failure, where a Chrome error page was read as
"Terms of Service removed" and the page's return the next day as "Terms of
Service launched".

- **`scripts/repair_legacy_analyses.py`** — flags any analysis with no `verdict`
  key as `legacy: true` (the current pipeline always writes a verdict; the old
  one never did) and replaces the model's date with `last_amended` from
  `hashes.json`. Idempotent; has a `--dry-run`. Applied: 6 files flagged,
  4 dates corrected.
- **`scripts/retract_analysis.py`** — retracts one analysis by set name, with a
  required `--reason` and an optional `--amended` to roll `last_amended` back.
  Writes a stub in the shape `steward/analysis.py` produces, archives the
  original into `logs/`, and clears the badge in `hashes.json`. Applied to
  Perplexity; `last_amended` rolled back from 9 August to 3 August, the last
  recorded change that is not part of the known-bad pair.
- **`src/components/PolicyDetail.js`** — a red banner for a retracted analysis
  and a grey one for a legacy analysis. Neither hides the content; both stop it
  reading as a current finding.

**A judgement call you may want to revisit.** Entries before 13 August 2026
predate the validation gates and have **not** been individually audited. The
3 August Perplexity "critical" that `last_amended` now points at is itself
probably the rotating privacy-notice banner that `steward_config.yaml` now
strips under `per_source_noise`. Rolling further back would have meant
adjudicating a series of analyses on no evidence, so the retraction text says
plainly that older entries are unaudited. If you want to go further, the
archive is all in `logs/` and `scripts/retract_analysis.py` takes any set name.

### 2.2 Two sources had never been read, for 35 runs (§3.2)

**`Digital.gov.au AI Policy` — disabled, not deleted.** The site serves a
bot-protection interstitial to datacentre IPs, including GitHub Actions
runners. Every capture since the source was added was that interstitial. Both
rungs of the escalation ladder (plain fetch, then Selenium) come from the same
blocked IP, and no proxy is configured, so there is nothing the pipeline can do
about it. It is now `"enabled": false` in `policy_sets.json` with a
`disabled_reason` naming the remedy.

**`NSW Government AI Guidance` — URL replaced.** The assurance-framework URL
404s; NSW restructured the section. Now points at
`.../ai-governance-assurance-and-frameworks/nsw-ai-assessment-framework`,
verified live (HTTP 200, 6,103 characters extracted, and a clean
`--dry-run` through the real pipeline).

**The ASBFEO URL is gone.** `asbfeo.gov.au/disputes-assistance/dispute-support`
was filed inside the NSW set. It is federal, it is not AI policy, and at 85 kB
against the real NSW page's 12 kB it dominated that set's diff surface.

**Seven new WAF signatures** in `steward_config.yaml`. Until these were listed,
the only thing between a bot-protection page and a stored baseline was
`validation.min_length` — and the digital.gov.au interstitial measures 256
characters from one host and 522 from another, i.e. on the wrong side of the
500 floor half the time. Verified: `check_failure_signature` now catches it.

### 2.3 `enabled: false` — a source can be off without being deleted (§5.5)

Deleting a set orphans its snapshots, diffs and archived analyses — `logs/` is
full of evidence from the last time that happened. So disabling keeps
everything and changes only what the system claims:

| Layer | Behaviour |
|---|---|
| `main.py` | `is_enabled()`, `disabled_entry()`; disabled sets are partitioned out before the processing loop and get an entry carrying prior state plus `monitoring: "disabled"`, `disabled_reason`, `disabled_since` |
| `steward/health.py` | a disabled source reports `status: "disabled"`, raises **no alert**, and does not drag `overall` down; `monitored_sources` counts only live ones |
| Frontend | its own "Not currently monitored" section on the dashboard, a grey pill, and a notice on the detail page carrying the reason |

`disabled_since` is preserved across runs rather than restamped, so it records
when monitoring stopped rather than when the last run happened.

### 2.4 Alerts fire on transitions, not states (§3.10)

This is why the two broken sources sat for a month: the workflow commented on
the same issue every single run, ~35 times, with the same table.

`steward/health.py` now keeps **`health_state.json`** (committed — it is added
to the workflow's `git add` list) recording what has already been reported:

- **New** — a source that started failing. Reported.
- **Recovered** — an alert that is gone. Reported. Previously nothing ever told
  you a source came back.
- **Still open** — repeated at most once every `health.digest_days` (7,
  configurable, validated).
- `alert_key()` is deliberately coarse — `kind|set_name|url`, excluding the
  detail text and the failure count — so tomorrow's failure with one more on
  the counter is the same alert, not a new one.

The state file is written whether or not an alert is raised, so a recovery is
still detected after a silent run.

### 2.5 The workflow can no longer be killed mid-write (§3.8)

`concurrency.cancel-in-progress` was `true` on the `pages` group, so a push to
`main` killed a scheduled run partway through. `main.py` writes snapshots during
its loop but `hashes.json` only at the end; a run killed in between leaves a
snapshot newer than the hash recorded for it, and the next run reads that as
"no change" — **silently swallowing a real one**. Now `false`.

The deeper fix (staging snapshots, or writing `hashes.json` per set) is **not
done** — see §4.

---

### 2.6 Week 1 — closing the feedback gaps (§3.3, §3.5, §3.6, §3.7, §3.11a)

**`steward/policy_sets.py` now owns the source list.** `validate_policy_sets`,
`is_enabled`, `disabled_entry`, `slugify_set_name` and a new `partition()` and
`validate_entry()` moved out of `main.py`. `validate_entry` returns *(ok,
reason)* rather than only logging, because the pipeline skips a bad entry and
carries on while an editor needs to show the reason to whoever typed it. This
was the prerequisite for the GUI: a second writer of `policy_sets.json` would
otherwise have arrived with a second copy of the rules.

**Link rot is its own outcome.** A 404 or 410 now returns `fetching.GONE`,
which is *terminal*: no Selenium launch, no proxy retry, no second attempt —
all three would be told the same thing, ~20 seconds and one Chrome launch
later. It surfaces as `link_rot` in `hashes.json`, as a `source_gone` health
alert with its own section in the issue body ("these returned 404 or 410 …
update the URL in `policy_sets.json`"), and as its own notice on the detail
page. It also **fails a document on the first run** rather than after three:
a 404 is deterministic, so waiting only delays the person who has to find the
new URL. This is what the NSW failure needed — it spent 35 runs reported as
"This site can't be reached".

**A failed call and a bad answer are now different failures.** `analyse_change`
retries an API error up to three times with exponential backoff and jitter
(2s/8s/30s), and a schema violation once with the error quoted back. Only a
genuine schema violation increments `schema_failures`; API errors get their own
`api_failures` counter and their own `api_failed` run-log outcome. The two
September 503s would no longer raise "the model returned an invalid response".

**The Gemini call is constrained, not just checked.** `RESPONSE_SCHEMA` pins
all four keys and both enums at generation time. `parse_and_validate` stays as
the belt to that braces and because a schema cannot express "declining sets
priority to low". The SDK import also moved inside the `client is None` branch
and `types.GenerateContentConfig` was replaced with a plain dict — the SDK
declares `GenerateContentConfigOrDict` and its `Type` enum is case-insensitive,
both verified against the installed source. That restores the `steward/`
contract: the module is now testable with an injected client and no SDK
present, which it was not before.

**A staleness banner watches the watcher.** `src/components/StaleRunNotice.js`
reads `health.json`'s `generated_at` and warns above the whole app when no run
has completed in 48 hours. A missing or unreadable health report counts as
stale, not fine — the absence of evidence is exactly the case being guarded
against. Nothing previously noticed if the workflow itself stopped: every badge
would freeze at its last value and the dashboard would look entirely normal.

## 3. Current data state

```
overall health   ok          (was "failing")
monitored        7 sets      (8 configured, 1 deliberately disabled)
alerts           0           (was 5, repeating daily)
poisoned baselines  0        (was 6: four 347-359 char WAF pages, one 84-char
                              error page, one orphaned ASBFEO record)
history.json     193 entries (192 + the newly archived Perplexity retraction)
```

`health.json`, `health_state.json` and `history.json` were regenerated locally
from the repaired `hashes.json` using the pipeline's own pure functions
(`health.build_report`, `history.build_index`) — no network, no model call, no
hand-editing. `hashes.json` was edited only through the two scripts in
`scripts/`, plus a seeding pass that calls `main.disabled_entry` directly so the
committed state is correct before the next run rather than after it.

**One deliberate departure from `CLAUDE.md`.** That file says never hand-craft
an `analysis/*.json`. Repairing four hallucinated dates and retracting a false
critical cannot be done any other way — no future run will overwrite those files,
because those sources have not materially changed. Both scripts write the exact
shape `steward/analysis.py` produces (`main.py` already hand-builds the same
shape for a first scan), and the originals are preserved in `logs/`. If you
disagree with that call, `git revert` the second commit; nothing else depends
on it.

---

## 4. Deliberately not done

Everything below is from `REVIEW_2026-09.md` and is **still open**.

| § | Item | Note |
|---|---|---|
| 3.4 | Priority inflation | Untouched, and now the largest open correctness problem. Still 48 criticals in 192 archived analyses. Needs few-shot anchors drawn from the archive, a required `evidence` field quoting the clause the rating rests on, and a `confidence` field. |
| 3.8 | Atomic snapshot/`hashes.json` writes | Only the CI cancellation was fixed. The underlying non-atomicity remains: a run that dies between the snapshot writes and the `hashes.json` write can still silently swallow a change. |
| 3.9 | Validator biased toward silence | `growth_ratio: 2.5` still rejects a doubled policy — the very event worth catching. `min_length` is still global. First captures still have no quarantine. |
| 3.11 | The remaining smaller items | b (mixed-case priorities in the archive), c (`git pull --rebase` with no conflict handling), d (uninformative commit messages), e (per-document priorities), f (nested interactive elements), g (deep-linked history), h (full-text search), i (global timeline), j (print stylesheet). Item a is done. |
| 5 | The source-editor GUI | Not started. `steward/policy_sets.py` now exists, which was the prerequisite. Design is in the review. |
| 6 | The news feed | Not started. **This is the next thing to build.** Design is in the review; do RSS before email. |

## 5. Watch this on the first real run

1. **`Digital.gov.au AI Policy` is skipped.** Expect one log line naming the
   reason and no fetch attempt. Its `hashes.json` entry already carries
   `monitoring: "disabled"`, so nothing should change.
2. **The NSW assessment framework is a first capture.** Its baseline was reset,
   so expect outcome `new`, a snapshot written, and **no** change reported for
   it. The set will still make one model call, because
   `generative-ai-basic-guidance` has a genuine `+1` line diff pending (seen in
   the dry run). That is correct behaviour, not a regression.
3. **`health_state.json` starts empty**, so the first run that produces any
   alert will report it as new. Expected once, not a bug.
4. **No health issue should be filed at all** if nothing transitions. If the
   workflow files one anyway, check that `health_state.json` is actually being
   committed — the `git add` loop in `update_checker.yml` is where that happens,
   and if the file is not persisted every run looks like a fresh start and the
   old behaviour returns silently.
5. **`Perplexity AI Legal Policies` should stay quiet.** If it produces a change,
   read the diff before believing it.

---

## 6. Where to pick up

Week 1 is done. The next block is the news feed, RSS first — `REVIEW_2026-09.md`
§6.1 explains why RSS before email, and §9 has the sequence.

1. **`feeds.yaml` + `steward/feeds.py`** — fetch and parse with `feedparser`
   (needs adding to `requirements.txt`), dedupe on entry id/link. Pure module,
   same testability contract as the rest of `steward/`.
2. **`steward/news.py`** — one model call per batch returning TLDR, topics and
   an `aps_relevance` band. Reuse the `AnalysisOutcome` error-kind split and the
   backoff that `steward/analysis.py` now has rather than writing a second
   retry loop. **Validate that every `source_url` the model returns actually
   appears in the source document** — a model that invents a link is worse than
   one that omits it.
3. **`news/feed.json`** (rolling 30 days) + `news/archive/YYYY-MM.json`, a News
   tab, and the cross-link to monitored policy sets (§6.3 item 2 — the feature
   that makes this a steward's feed rather than an aggregator).
4. Then the Gmail/IMAP ingestion for feedless newsletters, which needs the
   account set up first.

Before starting, ask the user which feeds to carry — that is the one decision
that cannot be made from the codebase.

## 7. Operating notes

```bash
# Re-check for poisoned baselines or orphaned document records at any time.
python scripts/reset_poisoned_baselines.py --dry-run

# Re-check for unrepaired legacy analyses.
python scripts/repair_legacy_analyses.py --dry-run

# Retract a false positive.
python scripts/retract_analysis.py "Set Name" --reason "..." --amended <iso> --dry-run

# Both repair scripts and the full suite are covered by:
python -m unittest discover -s tests -v
```

**To re-enable digital.gov.au**, set `PROXY_HOST` / `PROXY_PORT` / `PROXY_USER`
/ `PROXY_PASS` as repository secrets (they are already passed through by the
workflow), then set `"enabled": true` and add `"force_proxy": true` to the set
in `policy_sets.json`. Delete its `documents` records first — they are empty
now, so it will baseline cleanly. If no proxy is available, the honest
alternative is to monitor the DTA's published policy documents instead of the
WAF-protected pages, which would also be more stable.

`tests/test_repair_scripts.py` contains two tests that assert properties of the
**live repository data** — that no stored baseline is below the validation floor,
and that no `hashes.json` document record is missing from `policy_sets.json`.
They will fail loudly if either problem comes back. That is intentional; they
are the regression tests for §3.2 and they are meant to be noisy.
