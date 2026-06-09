# Bug Report: AI Steward Dashboard

**Date:** 2026-06-09  
**Repository:** thomas-amann-ipaustralia/ai-steward-dashboard  
**Stack:** React 18 (JavaScript) + Python 3.11 (Selenium + Google Gemini API)

---

## Summary

This report documents bugs and issues found across the codebase, grouped by severity. Each finding includes the file path, line number, a description of the problem, and an actionable fix.

---

## Critical Bugs

### BUG-01 — Function called with wrong argument order (`main.py:427`)

**Severity:** Critical — Logic Error  
**File:** `main.py`, line 427

**Problem:**  
`log_previous_version` is defined as `(set_name, file_id, timestamp)` but is called as `(file_id, file_id, timestamp)`. The first positional argument (meant to be the human-readable policy set name) is always passed `file_id` instead. This causes archive log filenames to be named using the file ID slug twice rather than the intended set name.

```python
# Definition (line 105)
def log_previous_version(set_name: str, file_id: str, timestamp: str) -> None:
    # Uses set_name in: f"{set_name}_{log_timestamp}_analysis.json"

# Incorrect call (line 427)
log_previous_version(file_id, file_id, previous_entry["last_checked"])
```

**Fix:**
```python
log_previous_version(set_name, file_id, previous_entry["last_checked"])
```

---

### BUG-02 — Unguarded array access on `urls[0]` crashes on malformed data

**Severity:** Critical — Runtime Crash  
**Files:**
- `src/components/DashboardHome.js`, line 78
- `src/components/Sidebar.js`, line 128

**Problem:**  
Both components access `p.urls[0].url` directly. Although `usePolicySets.js` filters policies to require `urls.length > 0`, there is no type-system enforcement, and malformed data would cause an uncaught `TypeError: Cannot read properties of undefined (reading 'url')` that crashes the component tree.

```javascript
// DashboardHome.js:78
src={`https://www.google.com/s2/favicons?sz=16&domain_url=${p.urls[0].url}`}

// Sidebar.js:128
src={`https://www.google.com/s2/favicons?sz=16&domain_url=${policySet.urls[0].url}`}
```

**Fix:** Use optional chaining with a fallback:
```javascript
src={`https://www.google.com/s2/favicons?sz=16&domain_url=${p.urls?.[0]?.url ?? ''}`}
```

---

## High Severity Issues

### BUG-03 — `response` may be unbound in Gemini JSON error handler (`main.py:294`)

**Severity:** High — Secondary Runtime Error  
**File:** `main.py`, lines 294–301

**Problem:**  
The `json.JSONDecodeError` handler references `response.text`, but `response` is only assigned inside the `try` block. If an exception occurs before or during the API call, accessing `response` in the handler raises an `UnboundLocalError`, masking the original error entirely.

```python
except json.JSONDecodeError as e:
    return {
        "analysis": f"Raw text: {response.text[:500]}",  # 'response' may not exist
        ...
    }
```

**Fix:**
```python
except json.JSONDecodeError as e:
    raw = response.text[:500] if 'response' in dir() else 'unavailable'
    return {
        "analysis": f"Raw text: {raw}",
        ...
    }
```

---

### BUG-04 — GitHub Actions workflow has no failure notification (`.github/workflows/update_checker.yml:79`)

**Severity:** High — Silent Failure  
**File:** `.github/workflows/update_checker.yml`, line 79

**Problem:**  
The workflow runs the Python script with no fallback or alerting on failure. If the script crashes (Gemini rate limit, Selenium crash, network error), the run fails silently. There is no notification to maintainers.

```yaml
run: |
  set -e
  python main.py
```

**Fix:** Add a failure notification step:
```yaml
- name: Run update script
  id: run_script
  continue-on-error: true
  run: python main.py

- name: Notify on failure
  if: steps.run_script.outcome == 'failure'
  run: |
    echo "::error::Update script failed. Check run logs."
    exit 1
```

---

### BUG-05 — Empty page content treated as valid, may trigger false change detection (`main.py:180`)

**Severity:** High — Data Integrity  
**File:** `main.py`, line 180

**Problem:**  
When a page body loads but contains no extractable text, an empty string `""` is returned. Downstream hash comparison logic treats this as valid content. If a page temporarily returns empty (e.g., CDN error, JS-heavy page that didn't render), it will hash as a "change" and trigger an AI analysis of empty content.

```python
return page_body.get_text(separator='\n', strip=True)  # May return ""
```

**Fix:** Return `None` for empty content, consistent with other failure paths:
```python
content = page_body.get_text(separator='\n', strip=True)
if not content:
    log.warning("    [%s] Page body empty after text extraction", driver_type)
    return None
return content
```

---

## Medium Severity Issues

### BUG-06 — `formatDate` does not detect invalid `Date` objects (`src/utils/constants.js:14`)

**Severity:** Medium — Incorrect UI Display  
**File:** `src/utils/constants.js`, lines 14–28

**Problem:**  
`new Date("invalid")` does not throw — it returns an invalid Date object. The `try/catch` block does not catch this, so invalid date strings render as `"Invalid Date"` in the locale string output rather than returning a controlled fallback.

```javascript
try {
  return new Date(dateString).toLocaleString('en-AU', {...});  // No NaN check
} catch {
  return dateString;
}
```

**Fix:**
```javascript
try {
  const date = new Date(dateString);
  if (isNaN(date.getTime())) return 'Unknown';
  return date.toLocaleString('en-AU', {...});
} catch {
  return 'Unknown';
}
```

---

### BUG-07 — URLs from policy data not validated before Selenium navigation (`main.py:136`)

**Severity:** Medium — Robustness / Security  
**File:** `main.py`, lines 136–142

**Problem:**  
URLs loaded from `policy_sets.json` are passed directly to `driver.get()` without scheme validation. A misconfigured or tampered entry with a `file://` or `javascript:` URL could cause unintended local file access or script execution within the browser context.

```python
url = url_data['url']  # No validation
driver.get(url)
```

**Fix:**
```python
from urllib.parse import urlparse

def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False

if not _is_safe_url(url):
    log.error("Skipping unsafe or invalid URL: %s", url)
    return None
```

---

### BUG-08 — Previous analysis not archived if `last_checked` is missing (`main.py:424`)

**Severity:** Medium — Data Loss  
**File:** `main.py`, line 424

**Problem:**  
`log_previous_version` is only called when `previous_entry.get("last_checked")` is truthy. If a prior entry exists but lacks `last_checked` (e.g., first run after a data migration), the previous analysis is silently overwritten without archiving.

```python
if previous_entry.get("last_checked"):
    log_previous_version(...)
```

**Fix:** Archive unconditionally when a previous entry exists:
```python
if previous_entry:
    log_previous_version(set_name, file_id, previous_entry.get("last_checked", timestamp))
```

---

### BUG-09 — Missing keyboard accessibility for `Space` key in `DashboardHome` (`src/components/DashboardHome.js:72`)

**Severity:** Medium — Accessibility (WCAG 2.1)  
**File:** `src/components/DashboardHome.js`, line 72

**Problem:**  
The keyboard handler only responds to `Enter`. WCAG 2.1 SC 2.1.1 requires interactive elements to be operable via both `Enter` and `Space`. `Sidebar.js` handles this correctly (line 120) but `DashboardHome.js` does not.

```javascript
// DashboardHome.js — incomplete
onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/policy/${p.file_id}`); }}

// Sidebar.js — correct
onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ... } }}
```

**Fix:**
```javascript
onKeyDown={(e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    navigate(`/policy/${p.file_id}`);
  }
}}
```

---

### BUG-10 — No fetch timeout causes indefinite loading state (`src/hooks/usePolicyDetail.js:23`)

**Severity:** Medium — User Experience  
**File:** `src/hooks/usePolicyDetail.js`, lines 23–60

**Problem:**  
`fetch()` calls have no timeout. If the GitHub Pages JSON files are slow or unavailable, the UI displays "Loading..." indefinitely with no user feedback.

**Fix:**
```javascript
const fetchWithTimeout = (url, ms = 10000) =>
  Promise.race([
    fetch(url),
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error('Request timed out')), ms)
    ),
  ]);
```

---

## Low Severity / Code Quality

### BUG-11 — `usePolicySets` computes `groupedSets` that is never used (`src/hooks/usePolicySets.js:39`)

**Severity:** Low — Dead Code  
**File:** `src/hooks/usePolicySets.js`, lines 39–46

**Problem:**  
The hook exports and computes `groupedSets` via `useMemo`, but `Sidebar.js` computes its own independent grouping from `filteredAndSorted` (line 51). The hook's computation is unused dead code.

**Fix:** Remove the unused `groupedSets` computation from `usePolicySets.js`, or consolidate the grouping logic into the hook and consume it in the sidebar.

---

### BUG-12 — `Date` objects constructed inside sort comparator (`src/components/Sidebar.js:40`)

**Severity:** Low — Minor Performance  
**File:** `src/components/Sidebar.js`, lines 40–43

**Problem:**  
Sort comparisons repeatedly call `new Date(...)`, constructing objects on every comparison pass.

```javascript
return new Date(b.last_amended || 0) - new Date(a.last_amended || 0);
```

**Fix:** Pre-compute timestamps before sorting:
```javascript
const withTs = filtered.map(p => ({ ...p, _ts: new Date(p.last_amended || 0).getTime() }));
withTs.sort((a, b) => b._ts - a._ts);
```

---

### BUG-13 — No PropTypes on any React component

**Severity:** Low — Maintainability  
**Files:** All files in `src/components/` and `src/hooks/`

**Problem:**  
No components define PropTypes. Combined with the lack of TypeScript, there is no static or runtime validation of prop shapes, making it easy to silently pass wrong data (e.g., `urls` without the required array structure).

**Fix:** Add PropTypes to each component, for example in `DashboardHome.js`:
```javascript
import PropTypes from 'prop-types';

DashboardHome.propTypes = {
  policySets: PropTypes.arrayOf(PropTypes.shape({
    file_id: PropTypes.string.isRequired,
    setName: PropTypes.string.isRequired,
    urls: PropTypes.arrayOf(PropTypes.shape({ url: PropTypes.string.isRequired })).isRequired,
    last_checked: PropTypes.string.isRequired,
  })).isRequired,
};
```

---

### BUG-14 — No test suite exists

**Severity:** Low — Maintainability  
**Files:** No `*.test.js`, `*.spec.js`, or `test_*.py` files found anywhere

**Problem:**  
There are zero automated tests. `npm test` launches an interactive runner with nothing to run. Critical logic (hash comparison, date formatting, Gemini parsing) has no coverage.

**Fix:** Add at minimum:
- `src/utils/constants.test.js` — unit tests for `formatDate`, `truncateText`
- `src/hooks/usePolicySets.test.js` — hook tests with mock data
- `test_main.py` — unit tests for `compute_hash`, `load_snapshot`, `validate_policy_sets`

---

### BUG-15 — README is a single sentence with no setup instructions

**Severity:** Low — Documentation  
**File:** `README.md`

**Problem:**  
The README contains only one line of description. There are no installation steps, environment variable instructions, local development guide, or deployment notes. A new contributor cannot onboard without reading source code and the GitHub Actions workflow.

**Fix:** Expand the README to include:
- Prerequisites (Node.js version, Python version, Chrome)
- Environment setup (`.env.example` walkthrough)
- `npm install && npm start` for frontend
- `pip install -r requirements.txt && python main.py` for backend
- Deployment overview (GitHub Actions + Pages)

---

## Findings Summary

| ID | Severity | Location | Description |
|----|----------|----------|-------------|
| BUG-01 | Critical | `main.py:427` | Wrong argument passed to `log_previous_version` |
| BUG-02 | Critical | `DashboardHome.js:78`, `Sidebar.js:128` | Unguarded `urls[0]` access crashes on bad data |
| BUG-03 | High | `main.py:294` | `response` unbound in JSON error handler |
| BUG-04 | High | `update_checker.yml:79` | No failure notification in CI workflow |
| BUG-05 | High | `main.py:180` | Empty page content triggers false change detection |
| BUG-06 | Medium | `constants.js:14` | `formatDate` doesn't detect `Invalid Date` |
| BUG-07 | Medium | `main.py:136` | No URL scheme validation before Selenium navigation |
| BUG-08 | Medium | `main.py:424` | Previous analysis not archived when `last_checked` missing |
| BUG-09 | Medium | `DashboardHome.js:72` | `Space` key not handled (accessibility gap) |
| BUG-10 | Medium | `usePolicyDetail.js:23` | No fetch timeout causes perpetual loading |
| BUG-11 | Low | `usePolicySets.js:39` | `groupedSets` computed but never consumed |
| BUG-12 | Low | `Sidebar.js:40` | `Date` objects constructed inside sort comparator |
| BUG-13 | Low | `src/components/*` | No PropTypes on any React component |
| BUG-14 | Low | — | No automated test suite |
| BUG-15 | Low | `README.md` | README is a single sentence |

---

## Recommended Fix Order

### Sprint 1 — Immediate
1. **BUG-01** — Fix argument order in `log_previous_version` call (1-line change)
2. **BUG-02** — Add optional chaining for `urls?.[0]?.url` (2 files, 1-line each)
3. **BUG-03** — Guard `response` reference in Gemini error handler
4. **BUG-04** — Add CI failure notification step to workflow

### Sprint 2 — Short Term
5. **BUG-05** — Return `None` instead of `""` for empty page content
6. **BUG-06** — Add `isNaN` check in `formatDate`
7. **BUG-07** — Add URL scheme validation before Selenium navigation
8. **BUG-09** — Add `Space` key handler in `DashboardHome.js`

### Sprint 3 — Medium Term
9. **BUG-08** — Archive unconditionally when previous entry exists
10. **BUG-10** — Add fetch timeout to `usePolicyDetail`
11. **BUG-13** — Add PropTypes to React components
12. **BUG-15** — Expand README

### Ongoing / Backlog
13. **BUG-11** — Remove dead `groupedSets` from hook
14. **BUG-12** — Pre-compute sort timestamps
15. **BUG-14** — Add test suite
