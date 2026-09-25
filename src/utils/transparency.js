import { timestampOf } from './constants';

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Past this many days since the date a statement gives for itself, it is
 * flagged as dated. The Standard for AI transparency statements expects a
 * statement to be kept current; the flag is a prompt to look, not a finding.
 */
export const DATED_AFTER_DAYS = 365;

export const OBLIGATIONS = [
  { value: 'mandatory', label: 'Mandatory', description: 'Non-corporate Commonwealth entities under the AI Policy' },
  { value: 'voluntary', label: 'Voluntary', description: 'Corporate entities, defence and intelligence agencies that chose to publish' },
];

/** What each kind of event is called on the page. */
export const EVENT_LABELS = {
  added: 'Joined the register',
  removed: 'Left the register',
  relinked: 'Statement moved',
  updated: 'Statement updated',
  reworded: 'Reworded',
};

/**
 * Whether an event says something about how an agency uses AI, or about who
 * has published. A statement reworded without changing its substance — a new
 * review date, a new contact address — is kept in the history but not
 * brought to anyone's attention.
 */
export const isNotable = (event) => Boolean(event) && event.type !== 'reworded';

export const eventsWithin = (events, days, now = Date.now()) =>
  (events || []).filter((event) => timestampOf(event.timestamp) > now - days * DAY_MS);

export const isNewEvent = (event, since) => Boolean(since) && timestampOf(event.timestamp) > since;

/** Days since the date a statement gives for itself, or null if it gives none. */
export const statementAgeDays = (statement, now = Date.now()) => {
  const at = timestampOf(statement?.statement_date);
  return at ? Math.floor((now - at) / DAY_MS) : null;
};

export const isDated = (statement, now = Date.now()) => {
  const age = statementAgeDays(statement, now);
  return age !== null && age > DATED_AFTER_DAYS;
};

export function filterStatements(statements, { query = '', obligation = '', portfolio = '', flag = '' } = {}, now = Date.now()) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return (statements || []).filter((statement) => {
    if (obligation && statement.obligation !== obligation) return false;
    if (portfolio && statement.portfolio !== portfolio) return false;
    if (flag === 'dated' && !isDated(statement, now)) return false;
    if (flag === 'undated' && statementAgeDays(statement, now) !== null) return false;
    if (flag === 'failing' && (statement.status || 'ok') === 'ok') return false;
    if (words.length) {
      const haystack = `${statement.agency} ${statement.portfolio} ${statement.url} ${statement.last_change?.summary || ''}`.toLowerCase();
      if (!words.every((word) => haystack.includes(word))) return false;
    }
    return true;
  });
}

export const SORTS = {
  portfolio: (a, b) => (a.portfolio || '').localeCompare(b.portfolio || '') || a.agency.localeCompare(b.agency),
  agency: (a, b) => a.agency.localeCompare(b.agency),
  changed: (a, b) =>
    timestampOf(b.last_change?.timestamp) - timestampOf(a.last_change?.timestamp) || a.agency.localeCompare(b.agency),
  oldest: (a, b) => {
    // A statement that gives no date sorts after every dated one.
    const at = (s) => timestampOf(s.statement_date) || Number.MAX_SAFE_INTEGER;
    return at(a) - at(b) || a.agency.localeCompare(b.agency);
  },
};
