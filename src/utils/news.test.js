import {
  dayLabel,
  filterItems,
  groupByDay,
  isNew,
  itemsForPolicy,
  rankItems,
  withinDays,
} from './news';
import { recordVisit, SESSION_GAP_MS } from './visits';
import { changeSummaryOf, revertedAfterChange } from './constants';
import { buildBriefing } from './briefing';

const NOW = new Date('2026-09-24T06:00:00Z').getTime();

const item = (id, overrides = {}) => ({
  id,
  kind: 'news',
  title: `Item ${id}`,
  url: `https://example.com/${id}`,
  category: 'Australian news',
  relevance: 2,
  published: '2026-09-23T00:00:00Z',
  first_seen: '2026-09-23T01:00:00Z',
  related_policies: [],
  ...overrides,
});

const incident = (id, country_code, overrides = {}) =>
  item(id, {
    kind: 'incident',
    category: 'AI incidents',
    incident: { country_code, harm_level: 'AI incident', industries: [], harmed_entities: [] },
    ...overrides,
  });

describe('filterItems', () => {
  const items = [
    item('a', { relevance: 3, title: 'Agency publishes AI transparency statement' }),
    item('b', { relevance: 1, category: 'AI providers' }),
    item('c', { related_policies: ['Anthropic_Legal_Policies'], published: '2026-09-24T00:00:00Z' }),
    incident('d', 'AUS'),
    incident('e', 'USA', { incident: { country_code: 'USA', harm_level: 'AI hazard', industries: ['Government, security, and defence'] } }),
  ];

  test('the default news view hides items rated below "Relevant"', () => {
    const shown = filterItems(items, { kind: 'news', minRelevance: 2 }).map((i) => i.id);
    expect(shown).toEqual(['c', 'a']);
  });

  test('search matches every word, in any field', () => {
    expect(filterItems(items, { query: 'transparency agency' }).map((i) => i.id)).toEqual(['a']);
    expect(filterItems(items, { query: 'transparency nonsense' })).toEqual([]);
  });

  test('category and related-policy filters', () => {
    expect(filterItems(items, { category: 'AI providers' }).map((i) => i.id)).toEqual(['b']);
    expect(filterItems(items, { relatedOnly: true }).map((i) => i.id)).toEqual(['c']);
  });

  test('incident scopes and harm levels', () => {
    expect(filterItems(items, { kind: 'incident', scope: 'australia' }).map((i) => i.id)).toEqual(['d']);
    expect(filterItems(items, { kind: 'incident', scope: 'government' }).map((i) => i.id)).toEqual(['e']);
    expect(filterItems(items, { kind: 'incident', harmLevel: 'AI hazard' }).map((i) => i.id)).toEqual(['e']);
  });

  test('tolerates a missing feed', () => {
    expect(filterItems(undefined, { kind: 'news' })).toEqual([]);
  });
});

describe('ordering and grouping', () => {
  test('rank puts relevance first, then reach', () => {
    const ranked = rankItems([
      item('low', { relevance: 1 }),
      item('quiet', { relevance: 3 }),
      item('loud', { relevance: 3, coverage: [{ url: 'x' }, { url: 'y' }] }),
    ]);
    expect(ranked.map((i) => i.id)).toEqual(['loud', 'quiet', 'low']);
  });

  test('groups by Sydney calendar day, preserving order', () => {
    // 23:30 UTC on the 23rd is the morning of the 24th in Sydney.
    const groups = groupByDay([
      item('x', { published: '2026-09-23T23:30:00Z' }),
      item('y', { published: '2026-09-23T15:00:00Z' }), // 1am on the 24th in Sydney
      item('z', { published: '2026-09-22T01:00:00Z' }),
    ]);
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([['x', 'y'], ['z']]);
  });

  test('day labels', () => {
    expect(dayLabel('2026-09-24T01:00:00Z', NOW)).toBe('Today');
    expect(dayLabel('2026-09-23T01:00:00Z', NOW)).toBe('Yesterday');
    expect(dayLabel('2026-09-20T01:00:00Z', NOW)).toMatch(/September/);
    expect(dayLabel(undefined, NOW)).toBe('Undated');
  });

  test('withinDays and itemsForPolicy', () => {
    const items = [
      item('old', { published: '2026-08-01T00:00:00Z' }),
      item('new', { related_policies: ['Google_AI_Policies'] }),
    ];
    expect(withinDays(items, 7, NOW).map((i) => i.id)).toEqual(['new']);
    expect(itemsForPolicy(items, 'Google_AI_Policies').map((i) => i.id)).toEqual(['new']);
  });
});

describe('new since the last visit', () => {
  const memory = () => {
    const store = {};
    return {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = String(v);
      },
    };
  };

  test('a first visit marks nothing new', () => {
    expect(recordVisit(memory(), NOW)).toBeNull();
    expect(isNew(item('a'), null)).toBe(false);
  });

  test('a reload in the same session keeps the same reference point', () => {
    const storage = memory();
    recordVisit(storage, NOW - 3 * 24 * 60 * 60 * 1000);
    const since = recordVisit(storage, NOW);
    expect(recordVisit(storage, NOW + SESSION_GAP_MS / 2)).toBe(since);
  });

  test('a later visit compares against the previous one', () => {
    const storage = memory();
    const earlier = NOW - 2 * 24 * 60 * 60 * 1000;
    recordVisit(storage, earlier);
    const since = recordVisit(storage, NOW);
    expect(since).toBe(earlier);
    expect(isNew(item('a', { first_seen: '2026-09-23T00:00:00Z' }), since)).toBe(true);
    expect(isNew(item('b', { first_seen: '2026-09-20T00:00:00Z' }), since)).toBe(false);
  });

  test('blocked storage is not an error', () => {
    const blocked = {
      getItem: () => {
        throw new Error('SecurityError');
      },
    };
    expect(recordVisit(blocked, NOW)).toBeNull();
  });
});

describe('change summaries', () => {
  test('a re-baseline review does not stand in for the change summary', () => {
    expect(
      changeSummaryOf({
        last_amended: '2026-09-13T00:00:00Z',
        last_review: { timestamp: '2026-09-20T00:00:00Z', summary: 'Baseline re-recorded.' },
      })
    ).toBeNull();
    expect(
      changeSummaryOf({
        last_amended: '2026-09-13T00:00:00Z',
        last_review: { timestamp: '2026-09-13T00:00:00Z', summary: 'Privacy policy expanded.' },
      })
    ).toBe('Privacy policy expanded.');
    expect(changeSummaryOf({ last_change: { summary: 'Recorded with the change.' } })).toBe('Recorded with the change.');
  });

  test('the briefing carries news and Australian incidents after the policies', () => {
    const text = buildBriefing({
      stableCount: 8,
      topNews: [item('n', { title: 'Senate inquiry into AI', publisher: 'ABC', tldr: 'An inquiry opened.' })],
      incidents: [incident('i', 'AUS', { title: 'Agent breaches portal' })],
    });
    expect(text.indexOf('In the news')).toBeGreaterThan(text.indexOf('Checked and unchanged'));
    expect(text).toContain('**Senate inquiry into AI** (ABC,');
    expect(text).toContain('An inquiry opened.');
    expect(text).toContain('Agent breaches portal');
  });
});

describe('reverted changes', () => {
  test('a revert after the badged change is surfaced', () => {
    const set = {
      last_amended: '2026-09-13T00:00:00Z',
      last_review: { verdict: 'reverted', timestamp: '2026-09-15T00:00:00Z' },
    };
    expect(revertedAfterChange(set)).toBe('2026-09-15T00:00:00Z');
  });

  test('anything else is not', () => {
    expect(revertedAfterChange({ last_review: { verdict: 'no_material_change', timestamp: '2026-09-15T00:00:00Z' } })).toBeNull();
    expect(revertedAfterChange({})).toBeNull();
  });
});
