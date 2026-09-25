import { timestampOf } from './constants';

/**
 * Helpers over news/feed.json — the news and AI-incident items the pipeline
 * gathers, gates and scores. Pure functions, so the views stay simple and the
 * filtering is testable without rendering anything.
 */

export const RELEVANCE = {
  3: { label: 'Highly relevant', description: 'Australian Government AI policy, guidance, legislation or incidents' },
  2: { label: 'Relevant', description: 'Providers APS staff use, comparable regulators, public-sector AI' },
  1: { label: 'Worth knowing', description: 'Major releases, research and wider AI news' },
};

export const TOPIC_LABELS = {
  government_policy: 'Government policy',
  regulation: 'Regulation & law',
  privacy: 'Privacy & data',
  security: 'Security',
  safety: 'Safety & incidents',
  vendors: 'AI providers',
  public_sector: 'Public sector use',
  workforce: 'Workforce & skills',
  research: 'Research',
};

export const NEWS_CATEGORIES = [
  'Australian Government',
  'Australian news',
  'Analysis',
  'International',
  'AI providers',
];

/** The headline sentence to show for an item: our summary, else the publisher's. */
export const blurbOf = (item) => item?.tldr || item?.summary || '';

export const isNew = (item, since) =>
  Boolean(since) && timestampOf(item?.first_seen) > since;

export const isAustralianIncident = (item) => item?.incident?.country_code === 'AUS';

export const isGovernmentIncident = (item) =>
  (item?.incident?.industries || []).some((i) => /government/i.test(i)) ||
  (item?.incident?.harmed_entities || []).some((e) => /government/i.test(e));

const matchesQuery = (item, query) => {
  if (!query) return true;
  const haystack = [
    item.title,
    item.tldr,
    item.summary,
    item.publisher,
    item.source_name,
    item.incident?.country,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
};

/**
 * Items matching every filter given, newest first.
 *
 * `scope` applies to incidents only: 'australia', 'government' or 'all'.
 */
export function filterItems(
  items,
  { kind, category, minRelevance = 0, query = '', relatedOnly = false, scope = 'all', harmLevel = '' } = {}
) {
  return (items || [])
    .filter((item) => !kind || item.kind === kind)
    .filter((item) => !category || item.category === category)
    .filter((item) => (item.relevance || 0) >= minRelevance)
    .filter((item) => !relatedOnly || (item.related_policies || []).length > 0)
    .filter((item) => {
      if (scope === 'australia') return isAustralianIncident(item);
      if (scope === 'government') return isGovernmentIncident(item);
      return true;
    })
    .filter((item) => !harmLevel || item.incident?.harm_level === harmLevel)
    .filter((item) => matchesQuery(item, query))
    .sort((a, b) => timestampOf(b.published) - timestampOf(a.published));
}

/** The Sydney calendar day of a timestamp, as YYYY-MM-DD. */
export const dayKey = (value) => {
  const time = timestampOf(value);
  if (!time) return 'undated';
  return new Date(time).toLocaleDateString('en-CA', { timeZone: 'Australia/Sydney' });
};

/** Items grouped by the Sydney calendar day they were published, in order. */
export function groupByDay(items) {
  const groups = [];
  const index = {};
  items.forEach((item) => {
    const key = dayKey(item.published);
    if (!(key in index)) {
      index[key] = groups.length;
      groups.push({ key, date: item.published, items: [] });
    }
    groups[index[key]].items.push(item);
  });
  return groups;
}

/** Most important first: relevance, then how widely reported, then recency. */
export function rankItems(items) {
  const reach = (item) => (item.coverage?.length || 0) + (item.incident?.articles || 0) / 50;
  return [...(items || [])].sort(
    (a, b) =>
      (b.relevance || 0) - (a.relevance || 0) ||
      reach(b) - reach(a) ||
      timestampOf(b.published) - timestampOf(a.published)
  );
}

/** Items published within the last `days` days. */
export function withinDays(items, days, now = Date.now()) {
  const cutoff = now - days * 24 * 60 * 60 * 1000;
  return (items || []).filter((item) => timestampOf(item.published) >= cutoff);
}

export function itemsForPolicy(items, fileId) {
  return rankItems((items || []).filter((item) => (item.related_policies || []).includes(fileId)));
}

/** "Today", "Yesterday", or a short weekday date, in Sydney time. */
export function dayLabel(value, now = Date.now()) {
  const key = dayKey(value);
  if (key === 'undated') return 'Undated';
  if (key === dayKey(new Date(now).toISOString())) return 'Today';
  if (key === dayKey(new Date(now - 24 * 60 * 60 * 1000).toISOString())) return 'Yesterday';
  return new Date(timestampOf(value)).toLocaleDateString('en-AU', {
    timeZone: 'Australia/Sydney',
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
}

/** The outlet a reader would name: the publisher, else the feed. */
export const publisherOf = (item) => item?.publisher || item?.source_name || '';

/** Whether an item's link goes through Google News rather than to the outlet. */
export const isAggregated = (item) => /^https?:\/\/news\.google\.com\//.test(item?.url || '');

/**
 * Up to three letters that identify an outlet at a glance: an acronym as
 * written (ABC, SBS, OECD), otherwise the initials of its first two words,
 * ignoring a leading "The".
 */
export function outletInitials(name) {
  const words = (name || '').replace(/^the\s+/i, '').split(/[\s—–-]+/).filter(Boolean);
  if (words.length === 0) return '?';
  const acronym = words[0].match(/^[A-Z]{2,4}(?![a-z])/);
  if (acronym) return acronym[0];
  return words
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join('');
}

/** Short relative time: "12m", "5h", then a date. */
export function formatAgo(value, now = Date.now()) {
  const time = timestampOf(value);
  if (!time) return '';
  const minutes = Math.max(0, Math.round((now - time) / 60000));
  if (minutes < 60) return `${Math.max(minutes, 1)}m ago`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)}h ago`;
  return new Date(time).toLocaleDateString('en-AU', {
    timeZone: 'Australia/Sydney',
    day: 'numeric',
    month: 'short',
  });
}

/**
 * The stories to lead with: highly relevant items, or anything widely reported,
 * from the last few days — most important first.
 */
export function pickTopStories(items, { days = 3, limit = 3, now = Date.now() } = {}) {
  return rankItems(withinDays(items, days, now))
    .filter((item) => item.relevance >= 3 || (item.coverage?.length || 0) >= 2)
    .slice(0, limit);
}
