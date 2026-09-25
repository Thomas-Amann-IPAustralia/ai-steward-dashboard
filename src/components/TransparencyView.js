import React, { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { BASE_URL, fetchWithTimeout, formatDay, formatRelative, safeHref } from '../utils/constants';
import {
  DATED_AFTER_DAYS,
  EVENT_LABELS,
  eventsWithin,
  filterStatements,
  isDated,
  isNewEvent,
  isNotable,
  OBLIGATIONS,
  SORTS,
} from '../utils/transparency';
import DiffView from './DiffView';
import { NewBadge } from './FeedCards';
import Icon from './Icon';
import Lettermark from './Lettermark';
import { HealthPill } from './SourceHealth';

const EVENT_LIMIT = 12;
const RECENT_DAYS = 30;

const SORT_OPTIONS = [
  { value: 'portfolio', label: 'Portfolio' },
  { value: 'changed', label: 'Recently changed' },
  { value: 'oldest', label: 'Oldest statement date' },
  { value: 'agency', label: 'Agency' },
];

const FLAGS = [
  { value: '', label: 'All statements' },
  { value: 'dated', label: `Dated over ${DATED_AFTER_DAYS / 365 === 1 ? 'a year' : `${DATED_AFTER_DAYS} days`} ago` },
  { value: 'undated', label: 'No date given' },
  { value: 'failing', label: 'Not read cleanly' },
];

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString('en-AU')} ${n === 1 ? one : many}`;

/** The last analysed diff of one statement, fetched when it is asked for. */
function StatementDiff({ id }) {
  const [state, setState] = useState({ diff: '', loading: true, error: false });

  useEffect(() => {
    const controller = new AbortController();
    fetchWithTimeout(`${BASE_URL}/transparency/diffs/${encodeURIComponent(id)}.diff?v=${Date.now()}`, {
      signal: controller.signal,
    })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(`Status ${response.status}`))))
      .then((diff) => setState({ diff, loading: false, error: false }))
      .catch((err) => {
        if (err.name !== 'AbortError') setState({ diff: '', loading: false, error: true });
      });
    return () => controller.abort();
  }, [id]);

  if (state.loading) return <div className="skeleton skeleton-list" />;
  if (state.error || !state.diff) return <p className="muted">The changed lines are not available.</p>;
  return <DiffView diff={state.diff} />;
}

function StatementItem({ statement, since, now }) {
  const [showDiff, setShowDiff] = useState(false);
  const change = statement.last_change;
  const fresh = change && isNewEvent({ timestamp: change.timestamp }, since);
  const dated = isDated(statement, now);
  const document = statement.document || {};

  return (
    <li className="review-item statement-item">
      <Lettermark url={statement.url} name={statement.agency} size={32} />
      <div className="review-main">
        <div className="review-head">
          <a className="review-name" href={safeHref(statement.url)} target="_blank" rel="noopener noreferrer">
            {statement.agency}
            <Icon name="external" size={13} className="inline-icon" />
          </a>
          {statement.obligation === 'voluntary' && <span className="obligation-chip">Voluntary</span>}
          {fresh && <NewBadge />}
          <HealthPill status={statement.status} />
        </div>
        <div className="review-meta">
          <span>{statement.portfolio || 'No portfolio listed'}</span>
          <span className={dated ? 'dated-flag' : undefined}>
            <Icon name="calendar" size={13} />
            {statement.statement_date ? `Statement dated ${formatDay(statement.statement_date)}` : 'Gives no date'}
            {dated && ' — over a year ago'}
          </span>
        </div>
        {change ? (
          <>
            <p className="review-summary">
              {change.verdict === 'no_material_change' && <span className="reworded-label">Reworded: </span>}
              {change.summary}
            </p>
            <div className="review-meta">
              <span>
                <Icon name="clock" size={13} /> Changed {formatRelative(change.timestamp)}
              </span>
              <button type="button" className="inline-link" onClick={() => setShowDiff((value) => !value)} aria-expanded={showDiff}>
                {showDiff ? 'Hide what changed' : 'Show what changed'}
              </button>
            </div>
            {showDiff && (
              <div className="statement-diff">
                <StatementDiff id={statement.id} />
              </div>
            )}
          </>
        ) : (
          <p className="review-summary muted">
            {document.last_success
              ? `No change since monitoring began ${formatRelative(statement.first_seen)}.`
              : 'Not read successfully yet.'}
          </p>
        )}
        {statement.status && statement.status !== 'ok' && document.last_error && (
          <p className="document-error">{document.last_error}</p>
        )}
        {document.route === 'archive' && document.archived_at && (
          <p className="document-note">
            The agency's site refused every direct read, so this was read from the Internet Archive's copy of{' '}
            {formatDay(document.archived_at)}.
          </p>
        )}
      </div>
    </li>
  );
}

function EventItem({ event, since }) {
  return (
    <li className="review-item event-item">
      <span className={`event-type event-${event.type}`}>{EVENT_LABELS[event.type] || event.type}</span>
      <div className="review-main">
        <div className="review-head">
          <a className="review-name" href={safeHref(event.url)} target="_blank" rel="noopener noreferrer">
            {event.agency}
          </a>
          {isNewEvent(event, since) && <NewBadge />}
        </div>
        {event.summary && <p className="review-summary">{event.summary}</p>}
        <div className="review-meta">
          <span><Icon name="clock" size={13} /> {formatDay(event.timestamp)}</span>
          {event.portfolio && <span>{event.portfolio}</span>}
          {event.type === 'relinked' && event.previous_url && <span>Previously at {event.previous_url}</span>}
        </div>
      </div>
    </li>
  );
}

/**
 * AI transparency statements: what Commonwealth agencies say about their own
 * use of AI. Not a policy that binds the reader and not an incident, so it is
 * its own stream. The DTA's register says who has published; each statement
 * is then read and compared on its own, and a change is summarised in terms
 * of the agency's AI use.
 */
function TransparencyView({ data, loading, error, since }) {
  const [params, setParams] = useSearchParams();
  const [showAllEvents, setShowAllEvents] = useState(false);
  const [includeRewording, setIncludeRewording] = useState(false);
  // Fixed for the visit, so ages and "recent" windows do not shift under the reader.
  const [now] = useState(() => Date.now());

  const query = params.get('q') || '';
  const obligation = params.get('obligation') || '';
  const portfolio = params.get('portfolio') || '';
  const flag = params.get('flag') || '';
  const sort = SORTS[params.get('sort')] ? params.get('sort') : 'portfolio';

  const update = (key, value, fallback = '') => {
    const next = new URLSearchParams(params);
    if (value && value !== fallback) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const { statements, events, register } = data;

  const stats = useMemo(() => {
    const recent = eventsWithin(events, RECENT_DAYS, now);
    return {
      mandatory: statements.filter((s) => s.obligation === 'mandatory').length,
      voluntary: statements.filter((s) => s.obligation === 'voluntary').length,
      updated: recent.filter((e) => e.type === 'updated').length,
      register: eventsWithin(events, 90, now).filter((e) => ['added', 'removed', 'relinked'].includes(e.type)).length,
      dated: statements.filter((s) => isDated(s, now)).length,
      unread: statements.filter((s) => (s.status || 'ok') !== 'ok').length,
    };
  }, [statements, events, now]);

  const portfolios = useMemo(
    () => [...new Set(statements.map((s) => s.portfolio).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
    [statements]
  );

  const results = useMemo(
    () => [...filterStatements(statements, { query, obligation, portfolio, flag }, now)].sort(SORTS[sort]),
    [statements, query, obligation, portfolio, flag, sort, now]
  );

  const grouped = useMemo(() => {
    if (sort !== 'portfolio') return null;
    return results.reduce((groups, statement) => {
      const key = statement.portfolio || 'No portfolio listed';
      (groups[key] = groups[key] || []).push(statement);
      return groups;
    }, {});
  }, [results, sort]);

  const shownEvents = events.filter((event) => includeRewording || isNotable(event));
  const visibleEvents = showAllEvents ? shownEvents : shownEvents.slice(0, EVENT_LIMIT);

  return (
    <div className="page transparency-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Transparency statements</p>
          <h1>How agencies say they use AI</h1>
          <p className="page-sub">
            Every statement linked from the DTA's{' '}
            <a href={safeHref(register?.url) || 'https://www.digital.gov.au/policy/ai/list-of-transparency-statements'} target="_blank" rel="noopener noreferrer">
              central register of AI transparency statements
            </a>
            , read every day and compared on its own
            {register?.page_updated ? ` · register last updated ${formatDay(register.page_updated)}` : ''}
            {data.generated_at && !loading ? ` · checked ${formatRelative(data.generated_at)}` : ''}
          </p>
        </div>
      </header>

      {error && (
        <div className="callout callout-info">
          <Icon name="alert" size={18} className="callout-icon" />
          <div className="callout-body">{error}</div>
        </div>
      )}

      {register && register.status !== 'ok' && (
        <div className={`callout ${register.status === 'failing' ? 'callout-critical' : 'callout-warning'}`} role="status">
          <Icon name="alert" size={18} className="callout-icon" />
          <div className="callout-body">
            <strong>The register could not be read on the last check.</strong>
            <p>
              {register.last_error ? `${register.last_error}. ` : ''}
              The {plural(statements.length, 'statement')} already known are still being checked, but an agency that
              joined or left since {register.last_success ? formatDay(register.last_success) : 'monitoring began'} would
              not show here yet.
            </p>
          </div>
        </div>
      )}

      {!loading && statements.length > 0 && (
        <section className="stat-tiles" aria-label="At a glance">
          <div className="stat-tile">
            <span className="stat-tile-label">Statements</span>
            <span className="stat-tile-value">{statements.length}</span>
            <span className="stat-tile-sub">
              {stats.mandatory} mandatory · {stats.voluntary} voluntary
            </span>
          </div>
          <div className="stat-tile">
            <span className="stat-tile-label">Updated · {RECENT_DAYS} days</span>
            <span className="stat-tile-value">{stats.updated}</span>
            <span className="stat-tile-sub">Changed what they say about AI use</span>
          </div>
          <div className="stat-tile">
            <span className="stat-tile-label">Register changes · 90 days</span>
            <span className="stat-tile-value">{stats.register}</span>
            <span className="stat-tile-sub">Agencies joining, leaving or moving</span>
          </div>
          <button type="button" className="stat-tile as-button" onClick={() => update('flag', flag === 'dated' ? '' : 'dated')}>
            <span className="stat-tile-label">Dated over a year ago</span>
            <span className="stat-tile-value">{stats.dated}</span>
            <span className="stat-tile-sub">{flag === 'dated' ? 'Showing these · show all' : 'Show these'}</span>
          </button>
        </section>
      )}

      <section className="card" aria-labelledby="transparency-activity-title">
        <div className="card-head">
          <div>
            <h2 id="transparency-activity-title">Recent activity</h2>
            <p className="card-sub">
              Agencies joining or leaving the register, and statements whose account of AI use changed. The summaries are
              written by an AI model from the changed lines; the statement itself is the authority.
            </p>
          </div>
          <label className="toggle-label">
            <input type="checkbox" checked={includeRewording} onChange={(event) => setIncludeRewording(event.target.checked)} />
            Include rewording
          </label>
        </div>
        {shownEvents.length === 0 ? (
          <p className="muted">
            {loading
              ? 'Loading…'
              : 'Nothing yet. The first read of the register is a baseline; changes from then on will appear here.'}
          </p>
        ) : (
          <>
            <ul className="review-list">
              {visibleEvents.map((event) => (
                <EventItem key={`${event.timestamp}-${event.type}-${event.id}`} event={event} since={since} />
              ))}
            </ul>
            {shownEvents.length > EVENT_LIMIT && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowAllEvents((value) => !value)}>
                {showAllEvents ? 'Show fewer' : `Show all ${shownEvents.length}`}
              </button>
            )}
          </>
        )}
      </section>

      <div className="toolbar" role="search">
        <label className="input-with-icon grow">
          <Icon name="search" size={16} />
          <input
            type="search"
            placeholder="Search agencies and changes…"
            value={query}
            onChange={(event) => update('q', event.target.value)}
            aria-label="Search agencies and changes"
          />
        </label>
        <div className="segmented" role="group" aria-label="Obligation">
          {[{ value: '', label: 'All' }, ...OBLIGATIONS].map((option) => (
            <button
              key={option.value || 'all'}
              type="button"
              title={option.description}
              aria-pressed={obligation === option.value}
              onClick={() => update('obligation', option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <label className="select-wrap">
          <span className="visually-hidden">Portfolio</span>
          <select value={portfolio} onChange={(event) => update('portfolio', event.target.value)}>
            <option value="">All portfolios</option>
            {portfolios.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
          <Icon name="chevron-down" size={14} />
        </label>
        <label className="select-wrap">
          <span className="visually-hidden">Sort by</span>
          <select value={sort} onChange={(event) => update('sort', event.target.value, 'portfolio')}>
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>Sort: {option.label}</option>
            ))}
          </select>
          <Icon name="chevron-down" size={14} />
        </label>
      </div>
      <div className="chip-row" role="group" aria-label="Show">
        {FLAGS.map((option) => (
          <button
            key={option.value || 'all'}
            type="button"
            className={`filter-chip${flag === option.value ? ' active' : ''}`}
            aria-pressed={flag === option.value}
            onClick={() => update('flag', option.value)}
          >
            {option.label}
            {option.value === 'failing' && stats.unread > 0 && <span className="chip-count">{stats.unread}</span>}
          </button>
        ))}
      </div>

      <p className="result-count" aria-live="polite">
        {plural(results.length, 'statement')}
      </p>

      {loading && statements.length === 0 && <div className="skeleton skeleton-list" />}
      {!loading && results.length === 0 && !error && (
        <div className="empty-state card">
          <span className="empty-icon"><Icon name="search" size={20} /></span>
          <div>
            <strong>No statements match</strong>
            <p>Try a different search, obligation or portfolio.</p>
          </div>
        </div>
      )}

      {results.length > 0 && (
        <div className="card statement-card">
          {grouped ? (
            Object.entries(grouped).map(([name, group]) => (
              <section key={name} className="statement-group" aria-label={name}>
                <h2 className="list-group-label">{name}</h2>
                <ul className="review-list">
                  {group.map((statement) => (
                    <StatementItem key={statement.id} statement={statement} since={since} now={now} />
                  ))}
                </ul>
              </section>
            ))
          ) : (
            <ul className="review-list">
              {results.map((statement) => (
                <StatementItem key={statement.id} statement={statement} since={since} now={now} />
              ))}
            </ul>
          )}
        </div>
      )}

      <aside className="card legend-card">
        <h2>Reading these statements</h2>
        <dl className="legend-grid">
          <div>
            <dt>Mandatory</dt>
            <dd>Published by non-corporate Commonwealth entities, which the Policy for the responsible use of AI in government requires to publish one.</dd>
          </div>
          <div>
            <dt>Voluntary</dt>
            <dd>Published by corporate Commonwealth entities, defence or intelligence agencies, which the Policy does not require to.</dd>
          </div>
          <div>
            <dt>Statement updated</dt>
            <dd>The agency changed what it says about its use of AI: use cases, tools, governance or its accountable official.</dd>
          </div>
          <div>
            <dt>Reworded</dt>
            <dd>The wording, dates or contact details changed but the substance did not. Hidden from recent activity unless included.</dd>
          </div>
          <div>
            <dt>Statement date</dt>
            <dd>The latest date a statement gives for when it was updated or published. “Over a year ago” is a prompt to look, not a finding.</dd>
          </div>
        </dl>
        <p className="muted">
          Agencies are responsible for their own statements; the DTA maintains the register but does not validate them.
          Formatting changes and pages flipping between two versions are filtered out before anything is summarised.
        </p>
      </aside>
    </div>
  );
}

export default TransparencyView;
