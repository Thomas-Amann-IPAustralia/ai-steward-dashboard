import {
  RUN_STALE_AFTER_HOURS,
  daysSince,
  formatDate,
  hostOf,
  isStale,
  primaryUrl,
  runStaleness,
  timestampOf,
} from './constants';
import { buildBriefing } from './briefing';

describe('formatDate', () => {
  test('renders a valid ISO timestamp', () => {
    expect(formatDate('2026-08-13T12:00:00+10:00')).toMatch(/2026/);
  });

  test('returns Unknown rather than the literal string "Invalid Date"', () => {
    // `new Date('nonsense')` does not throw, so a try/catch never caught this
    // and the dashboard rendered "Invalid Date" to the reader.
    expect(formatDate('nonsense')).toBe('Unknown');
    expect(formatDate('')).toBe('Unknown');
    expect(formatDate(null)).toBe('Unknown');
    expect(formatDate(undefined)).toBe('Unknown');
    expect(formatDate('Unknown')).toBe('Unknown');
  });
});

describe('badge staleness', () => {
  const now = new Date('2026-08-13T00:00:00Z').getTime();

  test('a recent change is not stale', () => {
    expect(isStale('2026-08-01T00:00:00Z', now)).toBe(false);
  });

  test('a change from months ago is stale', () => {
    // The live dashboard had Anthropic wearing CRITICAL from 21 July onwards.
    expect(isStale('2026-07-21T00:00:00Z', now)).toBe(false);
    expect(isStale('2026-05-21T00:00:00Z', now)).toBe(true);
  });

  test('an unparseable date is treated as stale rather than fresh', () => {
    expect(isStale('2024-13-45T99:00:00Z', now)).toBe(true);
    expect(daysSince('nonsense', now)).toBeNull();
  });
});

describe('malformed policy data does not crash', () => {
  test('primaryUrl guards a missing urls array', () => {
    expect(primaryUrl({ urls: [{ url: 'https://example.gov.au' }] })).toBe('https://example.gov.au');
    expect(primaryUrl({ urls: [] })).toBe('');
    expect(primaryUrl({})).toBe('');
    expect(primaryUrl(null)).toBe('');
  });

  test('hostOf tolerates junk', () => {
    expect(hostOf('https://www.example.gov.au/policy')).toBe('example.gov.au');
    expect(hostOf('not a url')).toBe('');
  });

  test('timestampOf returns 0 for unusable values, keeping sorts stable', () => {
    expect(timestampOf('nonsense')).toBe(0);
    expect(timestampOf(undefined)).toBe(0);
    expect(timestampOf('2026-08-13T00:00:00Z')).toBeGreaterThan(0);
  });
});

describe('buildBriefing', () => {
  test('reports a quiet week as information rather than an empty section', () => {
    const text = buildBriefing({ recentChanges: [], failingSources: [], stableCount: 8 });
    expect(text).toContain('No policy changes detected.');
    expect(text).toContain('8 monitored policy sets were checked');
  });

  test('leads with failing sources', () => {
    const text = buildBriefing({
      recentChanges: [],
      failingSources: [{ setName: 'Broken Source', status: 'failing', last_success: null }],
      stableCount: 7,
    });
    expect(text.indexOf('Needs attention')).toBeLessThan(text.indexOf('Changes in the last 7 days'));
    expect(text).toContain('Broken Source');
    expect(text).toContain('never read successfully');
  });

  test('includes changed document names and a deep link', () => {
    const text = buildBriefing({
      recentChanges: [
        {
          setName: 'Anthropic Legal Policies',
          file_id: 'Anthropic_Legal_Policies',
          last_priority: 'high',
          last_amended: '2026-08-12T00:00:00Z',
          last_change: { changed_documents: ['Aup'] },
          last_review: { summary: 'The acceptable use policy was tightened.' },
        },
      ],
      failingSources: [],
      stableCount: 7,
    });
    expect(text).toContain('Anthropic Legal Policies — HIGH');
    expect(text).toContain('Documents: Aup');
    expect(text).toContain('#/policy/Anthropic_Legal_Policies');
  });
});

describe('runStaleness', () => {
  const HOUR = 60 * 60 * 1000;
  const now = new Date('2026-09-17T12:00:00+10:00').getTime();
  const hoursAgo = (n) => new Date(now - n * HOUR).toISOString();

  test('a recent run is not stale', () => {
    const { stale, hours } = runStaleness({ generated_at: hoursAgo(6) }, now);
    expect(stale).toBe(false);
    expect(hours).toBe(6);
  });

  test('a run just inside the window is not stale', () => {
    expect(runStaleness({ generated_at: hoursAgo(47) }, now).stale).toBe(false);
  });

  test('a run past the window is stale', () => {
    expect(runStaleness({ generated_at: hoursAgo(RUN_STALE_AFTER_HOURS) }, now).stale).toBe(true);
  });

  test('a missing health report is stale, not fine', () => {
    // The absence of evidence is the case being guarded against: if health.json
    // never loaded, the dashboard cannot vouch for anything it is showing.
    expect(runStaleness(null, now).stale).toBe(true);
    expect(runStaleness({}, now).stale).toBe(true);
    expect(runStaleness({ generated_at: 'nonsense' }, now).stale).toBe(true);
  });

  test('a stale report still reports how stale', () => {
    expect(runStaleness({ generated_at: hoursAgo(200) }, now).hours).toBe(200);
  });
});
