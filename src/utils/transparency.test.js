import { filterStatements, isDated, isNotable, SORTS } from './transparency';

const now = new Date('2026-09-25T00:00:00Z').getTime();

const statements = [
  {
    id: 'ip-australia',
    agency: 'IP Australia',
    portfolio: 'Industry, Science and Resources',
    obligation: 'mandatory',
    url: 'https://www.ipaustralia.gov.au/ai',
    statement_date: '2026-03-14',
    status: 'ok',
    last_change: { timestamp: '2026-09-20T00:00:00Z', summary: 'Added prior-art search.' },
  },
  {
    id: 'asio',
    agency: 'Australian Security Intelligence Organisation',
    portfolio: 'Home Affairs',
    obligation: 'voluntary',
    url: 'https://www.asio.gov.au/ai',
    statement_date: '2025-02-01',
    status: 'failing',
  },
  {
    id: 'afma',
    agency: 'Australian Fisheries Management Authority',
    portfolio: 'Agriculture, Fisheries and Forestry',
    obligation: 'mandatory',
    url: 'https://www.afma.gov.au/ai',
    statement_date: null,
  },
];

const ids = (list) => list.map((s) => s.id);

test('filters by obligation, portfolio and search, including the latest change', () => {
  expect(ids(filterStatements(statements, { obligation: 'voluntary' }, now))).toEqual(['asio']);
  expect(ids(filterStatements(statements, { portfolio: 'Home Affairs' }, now))).toEqual(['asio']);
  expect(ids(filterStatements(statements, { query: 'prior-art' }, now))).toEqual(['ip-australia']);
});

test('a statement dated over a year ago is flagged; one with no date is not dated', () => {
  expect(isDated(statements[1], now)).toBe(true);
  expect(isDated(statements[0], now)).toBe(false);
  expect(isDated(statements[2], now)).toBe(false);
  expect(ids(filterStatements(statements, { flag: 'dated' }, now))).toEqual(['asio']);
  expect(ids(filterStatements(statements, { flag: 'undated' }, now))).toEqual(['afma']);
  expect(ids(filterStatements(statements, { flag: 'failing' }, now))).toEqual(['asio']);
});

test('the oldest sort puts undated statements last', () => {
  expect(ids([...statements].sort(SORTS.oldest))).toEqual(['asio', 'ip-australia', 'afma']);
});

test('rewording is kept in the history but not brought to attention', () => {
  expect(isNotable({ type: 'updated' })).toBe(true);
  expect(isNotable({ type: 'added' })).toBe(true);
  expect(isNotable({ type: 'reworded' })).toBe(false);
});
