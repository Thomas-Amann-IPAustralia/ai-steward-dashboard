import { timestampOf } from './constants';
import { dayKey } from './news';

/**
 * Turning the feed, the history index and the daily activity into the
 * evenly spaced series the charts draw. Pure, so each chart's numbers can be
 * checked without rendering it, and a gap in the data stays a gap (a zero
 * day) instead of being silently closed up.
 */

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

/**
 * The last `days` Sydney calendar days, oldest first, as YYYY-MM-DD. Stepped
 * in half-days and de-duplicated, so a daylight-saving change can neither
 * skip a day nor repeat one.
 */
export function lastDays(days, now = Date.now()) {
  const keys = [];
  for (let t = now; keys.length < days; t -= 12 * HOUR_MS) {
    const key = dayKey(new Date(t).toISOString());
    if (keys[keys.length - 1] !== key) keys.push(key);
  }
  return keys.reverse();
}

/** Midday UTC on a YYYY-MM-DD day — a safe timestamp for labelling it. */
export const dayTime = (key) => Date.parse(`${key}T12:00:00Z`);

/**
 * Items counted per day over the last `days` days, split by `seriesOf(item)`.
 * Returns `[{ key, counts: { [series]: n }, total, items }]`, oldest first.
 */
export function dailySeries(items, { days, now = Date.now(), seriesOf = () => 'all', dateOf = (item) => item.published }) {
  const keys = lastDays(days, now);
  const index = Object.fromEntries(keys.map((key, i) => [key, i]));
  const rows = keys.map((key) => ({ key, counts: {}, total: 0, items: [] }));
  (items || []).forEach((item) => {
    const time = timestampOf(dateOf(item));
    if (!time) return;
    const at = index[dayKey(new Date(time).toISOString())];
    if (at === undefined) return;
    const series = seriesOf(item);
    rows[at].counts[series] = (rows[at].counts[series] || 0) + 1;
    rows[at].total += 1;
    rows[at].items.push(item);
  });
  return rows;
}

/**
 * The same, per week (Monday to Sunday, Sydney time), for sparse series such
 * as incidents where most days are zero. The last week is the current one.
 */
export function weeklySeries(items, { weeks, now = Date.now(), seriesOf = () => 'all', dateOf = (item) => item.published }) {
  const days = lastDays(weeks * 7 + 6, now);
  const weekOf = (key) => {
    const weekday = (new Date(dayTime(key)).getUTCDay() + 6) % 7; // Monday = 0
    return new Date(dayTime(key) - weekday * DAY_MS).toISOString().slice(0, 10);
  };
  const starts = [...new Set(days.map(weekOf))].slice(-weeks);
  const index = Object.fromEntries(starts.map((key, i) => [key, i]));
  const rows = starts.map((key) => ({ key, counts: {}, total: 0, items: [] }));
  (items || []).forEach((item) => {
    const time = timestampOf(dateOf(item));
    if (!time) return;
    const at = index[weekOf(dayKey(new Date(time).toISOString()))];
    if (at === undefined) return;
    const series = seriesOf(item);
    rows[at].counts[series] = (rows[at].counts[series] || 0) + 1;
    rows[at].total += 1;
    rows[at].items.push(item);
  });
  return rows;
}

/**
 * What one day of checks on a source amounted to, most telling first: a
 * material change, a change the model analysed and let pass, every read
 * failing, some reads failing, clean reads, or no run at all.
 */
export function dayStatus(day) {
  if (!day || !day.checks) return 'none';
  if (day.material) return 'material';
  if (day.analysed || day.changed) return 'change';
  const bad = (day.rejected || 0) + (day.failed || 0);
  if (bad >= day.checks) return 'failed';
  if (bad > 0) return 'partial';
  return 'ok';
}

export const DAY_STATUS_LABELS = {
  material: 'Material change',
  change: 'Change analysed, not material',
  failed: 'Not read',
  partial: 'Partly read',
  ok: 'Read, no change',
  none: 'No check recorded',
};

/** A source's daily activity laid over the last `days` days, gaps included. */
export function statusStrip(daily, { days = 30, now = Date.now() } = {}) {
  const byDay = Object.fromEntries((daily || []).map((day) => [day.date, day]));
  return lastDays(days, now).map((key) => ({ key, day: byDay[key] || null, status: dayStatus(byDay[key]) }));
}

/** The history index entries for one set that fall in [from, to], oldest first. */
export function eventsBetween(entries, from, to) {
  return (entries || [])
    .map((entry) => ({ ...entry, time: timestampOf(entry.timestamp) }))
    .filter((entry) => entry.time >= from && entry.time <= to)
    .sort((a, b) => a.time - b.time);
}

/** Whether an archived analysis recorded a change the model judged material. */
export const isMaterialEntry = (entry) =>
  !['no_material_change', 'rebaselined', 'reverted'].includes(entry?.verdict);
