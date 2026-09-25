import { dailySeries, dayStatus, eventsBetween, isMaterialEntry, lastDays, statusStrip, weeklySeries } from './series';

// 06:00 UTC on 24 September is 4pm in Sydney.
const NOW = new Date('2026-09-24T06:00:00Z').getTime();

describe('evenly spaced days', () => {
  test('the last n Sydney days, oldest first, ending today', () => {
    expect(lastDays(3, NOW)).toEqual(['2026-09-22', '2026-09-23', '2026-09-24']);
  });

  test('a daylight-saving change neither skips nor repeats a day', () => {
    // Sydney clocks go forward on 4 October 2026.
    const days = lastDays(5, new Date('2026-10-05T14:30:00Z').getTime());
    expect(new Set(days).size).toBe(5);
    expect(days).toEqual(['2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05', '2026-10-06']);
  });
});

describe('counting items per period', () => {
  const items = [
    { published: '2026-09-24T01:00:00Z', relevance: 3 },
    { published: '2026-09-23T23:30:00Z', relevance: 2 }, // the 24th in Sydney
    { published: '2026-09-22T01:00:00Z', relevance: 2 },
    { published: '2026-08-01T01:00:00Z', relevance: 3 }, // outside the window
    { published: 'nonsense', relevance: 3 },
  ];

  test('daily, split by series, with empty days kept', () => {
    const rows = dailySeries(items, { days: 3, now: NOW, seriesOf: (item) => item.relevance });
    expect(rows.map((row) => row.key)).toEqual(['2026-09-22', '2026-09-23', '2026-09-24']);
    expect(rows.map((row) => row.total)).toEqual([1, 0, 2]);
    expect(rows[2].counts).toEqual({ 2: 1, 3: 1 });
  });

  test('weekly, Monday to Sunday, ending with the current week', () => {
    const rows = weeklySeries(items, { weeks: 2, now: NOW });
    expect(rows.map((row) => row.key)).toEqual(['2026-09-14', '2026-09-21']);
    expect(rows.map((row) => row.total)).toEqual([0, 3]);
  });
});

describe('a day of checks on a source', () => {
  test('the most telling outcome wins', () => {
    expect(dayStatus(null)).toBe('none');
    expect(dayStatus({ checks: 3, unchanged: 3 })).toBe('ok');
    expect(dayStatus({ checks: 3, unchanged: 2, rejected: 1 })).toBe('partial');
    expect(dayStatus({ checks: 2, rejected: 1, failed: 1 })).toBe('failed');
    expect(dayStatus({ checks: 2, changed: 1, analysed: 1, declined: 1 })).toBe('change');
    expect(dayStatus({ checks: 2, rejected: 2, analysed: 1, material: 1 })).toBe('material');
  });

  test('the strip covers every day, marking the ones with no check', () => {
    const strip = statusStrip([{ date: '2026-09-24', checks: 1, unchanged: 1 }], { days: 3, now: NOW });
    expect(strip.map((cell) => cell.status)).toEqual(['none', 'none', 'ok']);
  });
});

describe('history events', () => {
  test('only those in range, oldest first; declined and re-baselined ones are not material', () => {
    const entries = [
      { timestamp: '2026-09-20T10:00:00', verdict: null },
      { timestamp: '2026-09-10T10:00:00', verdict: 'no_material_change' },
      { timestamp: '2026-01-01T10:00:00', verdict: null },
    ];
    const events = eventsBetween(entries, new Date('2026-09-01').getTime(), NOW);
    expect(events.map((e) => e.timestamp)).toEqual(['2026-09-10T10:00:00', '2026-09-20T10:00:00']);
    expect(events.map(isMaterialEntry)).toEqual([false, true]);
  });
});
