import { changeKey, isReviewed, loadReviewed, reviewQueue, saveReviewed, setReviewed } from './reviews';

const NOW = new Date('2026-09-25T00:00:00Z').getTime();

const set = (id, amended, overrides = {}) => ({
  file_id: id,
  setName: id,
  last_amended: amended,
  last_verdict: 'material_change',
  ...overrides,
});

const memory = () => {
  const store = {};
  return {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {
      store[k] = String(v);
    },
  };
};

describe('the review queue', () => {
  const sets = [
    set('recent', '2026-09-20T00:00:00Z'),
    set('older', '2026-09-10T00:00:00Z'),
    set('stale', '2026-07-01T00:00:00Z'),
    set('declined', '2026-09-22T00:00:00Z', { last_verdict: 'no_material_change' }),
    set('never', null),
  ];

  test('holds material changes from the last 30 days, newest first', () => {
    const { pending, done } = reviewQueue(sets, {}, { now: NOW });
    expect(pending.map((s) => s.file_id)).toEqual(['recent', 'older']);
    expect(done).toEqual([]);
  });

  test('an adoption register is never queued for review', () => {
    const register = set('register', '2026-09-23T00:00:00Z', { kind: 'adoption' });
    expect(reviewQueue([...sets, register], {}, { now: NOW }).pending.map((s) => s.file_id)).toEqual(['recent', 'older']);
  });

  test('a reviewed change moves out of the queue, and undo puts it back', () => {
    const reviewed = setReviewed({}, sets[0], true, NOW);
    expect(reviewQueue(sets, reviewed, { now: NOW }).pending.map((s) => s.file_id)).toEqual(['older']);
    expect(reviewQueue(sets, reviewed, { now: NOW }).done.map((s) => s.file_id)).toEqual(['recent']);
    expect(reviewQueue(sets, setReviewed(reviewed, sets[0], false), { now: NOW }).pending).toHaveLength(2);
  });

  test('reviewing one change does not hide the next change to the same set', () => {
    const reviewed = setReviewed({}, sets[0], true, NOW);
    const changedAgain = { ...sets[0], last_amended: '2026-09-24T00:00:00Z' };
    expect(isReviewed(reviewed, sets[0])).toBe(true);
    expect(isReviewed(reviewed, changedAgain)).toBe(false);
    expect(changeKey(changedAgain)).toBe('recent@2026-09-24T00:00:00Z');
  });
});

describe('remembering reviews', () => {
  test('round-trips through storage', () => {
    const storage = memory();
    saveReviewed(storage, setReviewed({}, set('a', '2026-09-20T00:00:00Z'), true, NOW));
    expect(isReviewed(loadReviewed(storage), set('a', '2026-09-20T00:00:00Z'))).toBe(true);
  });

  test('corrupt or blocked storage means nothing is remembered, not an error', () => {
    const corrupt = memory();
    corrupt.setItem('steward.reviewed', 'not json');
    expect(loadReviewed(corrupt)).toEqual({});
    expect(loadReviewed({ getItem: () => { throw new Error('SecurityError'); } })).toEqual({});
    expect(() => saveReviewed({ setItem: () => { throw new Error('QuotaExceeded'); } }, {})).not.toThrow();
  });
});
