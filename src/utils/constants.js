export const BASE_URL = process.env.PUBLIC_URL || '/ai-steward-dashboard';

export const REPO_URL = 'https://github.com/Thomas-Amann-IPAustralia/ai-steward-dashboard';

/**
 * An external link's href, or undefined unless it is plain http(s).
 *
 * Every URL the dashboard links to comes from a data file, and React renders
 * a `javascript:` href as a working link (it only warns). The pipeline
 * validates schemes too; this is the check at the point of use, so one bad
 * entry becomes an unlinked label rather than a script.
 */
export const safeHref = (url) => {
  if (typeof url !== 'string') return undefined;
  try {
    const { protocol } = new URL(url);
    return protocol === 'http:' || protocol === 'https:' ? url : undefined;
  } catch {
    return undefined;
  }
};

export const PRIORITY_COLORS = {
  critical: '#dc2626',
  high: '#ea580c',
  medium: '#d97706',
  low: '#16a34a',
};

export const PRIORITY_ORDER = ['critical', 'high', 'medium', 'low'];

export const getPriorityColor = (priority) =>
  PRIORITY_COLORS[priority?.toLowerCase()] || '#6b7280';

/**
 * A priority badge describes a change that happened on a date. Left undated it
 * reads as a permanent property of the source, which trains people to ignore
 * it — Anthropic wore CRITICAL from 21 July onwards. After STALE_AFTER_DAYS
 * the badge is shown faded and always carries its date.
 */
export const STALE_AFTER_DAYS = 30;

export const isStale = (isoDate, now = Date.now()) => {
  const days = daysSince(isoDate, now);
  return days === null || days > STALE_AFTER_DAYS;
};

export const daysSince = (isoDate, now = Date.now()) => {
  const parsed = toDate(isoDate);
  if (!parsed) return null;
  return Math.floor((now - parsed.getTime()) / (24 * 60 * 60 * 1000));
};

/**
 * Whose policy a set is: government (Commonwealth or state) or the private
 * sector, read from the category policy_sets.json gives it. Anything else —
 * a category added later — is left out of both filters rather than guessed.
 */
export const SECTORS = [
  { value: 'government', label: 'Government' },
  { value: 'private', label: 'Private sector' },
];

export const sectorOf = (set) => {
  const category = (set?.category || '').toLowerCase();
  if (category.includes('government')) return 'government';
  if (category.includes('private')) return 'private';
  return null;
};

export const VERDICT_LABELS = {
  material_change: 'Material change',
  no_material_change: 'No material change',
  uncertain: 'Uncertain',
  rebaselined: 'Baseline re-recorded',
  reverted: 'Returned to an earlier version',
};

export const PRIORITY_DESCRIPTIONS = {
  critical: 'Directly alters user rights, data handling, liability or legal obligations',
  high: 'A significant shift in how the service operates or is governed',
  medium: 'Notable but not urgent — clarifications or minor scope changes',
  low: 'Cosmetic or trivial wording with no practical impact',
};

/** Plain-language names for a document's state on its last check. */
export const DOCUMENT_STATES = {
  unchanged: 'Unchanged',
  not_modified: 'Unchanged (server confirmed)',
  changed: 'Changed',
  cosmetic: 'Reformatted only',
  reverted: 'Back to an earlier version',
  new: 'First capture',
  rebaselined: 'Baseline re-recorded',
  suspect_scrape: 'Capture rejected',
  fetch_failed: 'Could not be read',
  analysis_pending: 'Change awaiting analysis',
};

/**
 * When a set's last badged change has since been reverted — the document
 * went back to a version recorded before it — the time that happened, else
 * null. The badge stays (the change did happen), but the reader is told.
 */
export const revertedAfterChange = (set) => {
  const review = set?.last_review;
  if (review?.verdict !== 'reverted') return null;
  return timestampOf(review.timestamp) > timestampOf(set?.last_amended) ? review.timestamp : null;
};

/**
 * The one-line summary of a set's most recent badged change.
 *
 * `last_review` moves on every analysis, badged or not — including a
 * re-baseline — so it is only used when it describes that same change. The
 * set's latest analysis file, when the caller has it, is used on the same
 * terms: only if it was written for the change the set is badged with.
 */
export const changeSummaryOf = (set, analysis = null) => {
  if (set?.last_change?.summary) return set.last_change.summary;
  const review = set?.last_review;
  if (review?.summary && review.timestamp && review.timestamp === set?.last_amended) {
    return review.summary;
  }
  if (
    analysis?.summary &&
    analysis.verdict !== 'no_material_change' &&
    timestampOf(analysis.date_time) &&
    timestampOf(analysis.date_time) === timestampOf(set?.last_amended)
  ) {
    return analysis.summary;
  }
  return null;
};

export const HEALTH_LABELS = {
  ok: 'Reading normally',
  degraded: 'Last read failed',
  failing: 'Not being read',
};

const toDate = (value) => {
  if (!value || value === 'Unknown') return null;
  const parsed = new Date(value);
  // `new Date('nonsense')` does not throw — it returns an Invalid Date, which
  // renders as the literal string "Invalid Date" unless it is checked here.
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

export const formatDate = (dateString) => {
  const parsed = toDate(dateString);
  if (!parsed) return 'Unknown';
  return parsed.toLocaleString('en-AU', {
    timeZone: 'Australia/Sydney',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const formatDay = (dateString) => {
  const parsed = toDate(dateString);
  if (!parsed) return 'Unknown';
  return parsed.toLocaleDateString('en-AU', {
    timeZone: 'Australia/Sydney',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
};

export const formatShortDay = (dateString) => {
  const parsed = toDate(dateString);
  if (!parsed) return 'Unknown';
  return parsed.toLocaleDateString('en-AU', {
    timeZone: 'Australia/Sydney',
    month: 'short',
    day: 'numeric',
  });
};

export const formatRelative = (dateString) => {
  const days = daysSince(dateString);
  if (days === null) return 'Unknown';
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  if (days < 365) return `${Math.round(days / 30)} months ago`;
  return `${Math.round(days / 365)} years ago`;
};

export const timestampOf = (value) => {
  const parsed = toDate(value);
  return parsed ? parsed.getTime() : 0;
};

/** First URL of a policy set, guarded against malformed data. */
export const primaryUrl = (policySet) => policySet?.urls?.[0]?.url ?? '';

export const hostOf = (url) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
};

const FETCH_TIMEOUT_MS = 12000;

/**
 * fetch with a timeout. Without one the dashboard sits on "Loading..."
 * indefinitely whenever a data file is slow or missing.
 */
export const fetchWithTimeout = (url, { signal, timeout = FETCH_TIMEOUT_MS } = {}) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', () => controller.abort(), { once: true });
  }
  return fetch(url, { signal: controller.signal }).finally(() => clearTimeout(timer));
};
