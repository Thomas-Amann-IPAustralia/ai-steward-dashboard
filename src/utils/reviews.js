import { timestampOf } from './constants';

/**
 * The review queue: the one thing on this dashboard a steward acts on.
 *
 * News and incidents are for reading. A material change to a monitored
 * policy is different — someone should look at it and decide whether it
 * matters to their agency. Each change is keyed by its set and the moment it
 * happened, so marking Anthropic's 13 September change as reviewed does not
 * hide the next one. Remembered per browser, like the last-visit marker; a
 * blocked or unavailable storage simply means nothing is remembered.
 */

export const REVIEWED_KEY = 'steward.reviewed';

/** How far back an unreviewed change still asks for attention. */
export const REVIEW_WINDOW_DAYS = 30;

/** Enough for years of changes across every monitored set. */
const MAX_REMEMBERED = 200;

export const changeKey = (set) =>
  set?.file_id && set?.last_amended ? `${set.file_id}@${set.last_amended}` : null;

export function loadReviewed(storage) {
  try {
    const parsed = JSON.parse(storage?.getItem(REVIEWED_KEY) || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function saveReviewed(storage, reviewed) {
  const kept = Object.entries(reviewed)
    .sort(([, a], [, b]) => b - a)
    .slice(0, MAX_REMEMBERED);
  try {
    storage?.setItem(REVIEWED_KEY, JSON.stringify(Object.fromEntries(kept)));
  } catch {
    // Not remembered beyond this page load; the queue still works.
  }
  return Object.fromEntries(kept);
}

/** A copy of `reviewed` with the set's latest change marked, or unmarked. */
export function setReviewed(reviewed, set, done, now = Date.now()) {
  const key = changeKey(set);
  if (!key) return reviewed;
  const next = { ...reviewed };
  if (done) next[key] = now;
  else delete next[key];
  return next;
}

export const isReviewed = (reviewed, set) => {
  const key = changeKey(set);
  return Boolean(key && reviewed?.[key]);
};

/** Whether a set's latest change was judged material — the kind worth reviewing. */
export const hasMaterialChange = (set) =>
  Boolean(set?.last_amended) && set.last_verdict !== 'no_material_change';

/**
 * Sets whose latest material change falls within the review window, newest
 * first, split into those still to review and those already reviewed.
 */
export function reviewQueue(policySets, reviewed, { now = Date.now(), days = REVIEW_WINDOW_DAYS } = {}) {
  const cutoff = now - days * 24 * 60 * 60 * 1000;
  const recent = (policySets || [])
    .filter((set) => hasMaterialChange(set) && timestampOf(set.last_amended) > cutoff)
    .sort((a, b) => timestampOf(b.last_amended) - timestampOf(a.last_amended));
  return {
    pending: recent.filter((set) => !isReviewed(reviewed, set)),
    done: recent.filter((set) => isReviewed(reviewed, set)),
  };
}
