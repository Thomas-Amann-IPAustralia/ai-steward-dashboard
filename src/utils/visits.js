/**
 * "What's new since I last looked?" — the question a steward arrives with.
 *
 * The previous visit is remembered per browser in localStorage. A reload
 * within SESSION_GAP_MS counts as the same visit, so refreshing the page does
 * not wipe the "new" markers the reader has not finished reading.
 */

export const SESSION_GAP_MS = 30 * 60 * 1000;

const LAST_SEEN_KEY = 'steward.lastSeen';
const PREVIOUS_VISIT_KEY = 'steward.previousVisit';

/**
 * Returns the start of the previous visit (ms), or null on a first visit, and
 * records this one. Storage can be unavailable or throw — on managed devices
 * and in private windows — in which case nothing is marked new.
 */
export function recordVisit(storage, now = Date.now()) {
  try {
    const lastSeen = Number(storage.getItem(LAST_SEEN_KEY)) || 0;
    let previous = Number(storage.getItem(PREVIOUS_VISIT_KEY)) || 0;

    if (lastSeen && now - lastSeen > SESSION_GAP_MS) {
      previous = lastSeen;
      storage.setItem(PREVIOUS_VISIT_KEY, String(previous));
    }
    storage.setItem(LAST_SEEN_KEY, String(now));
    return previous || null;
  } catch {
    return null;
  }
}
