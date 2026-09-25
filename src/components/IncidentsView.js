import React, { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { formatRelative, formatShortDay } from '../utils/constants';
import { filterItems, isAustralianIncident, isGovernmentIncident, isNew } from '../utils/news';
import { dayTime, weeklySeries } from '../utils/series';
import { Legend, StackedColumns } from './charts';
import { IncidentCard } from './FeedCards';
import Icon from './Icon';

const PAGE_SIZE = 30;
const WEEKS = 8;

const SCOPES = [
  { value: 'australia', label: 'In Australia' },
  { value: 'government', label: 'Government, worldwide' },
  { value: 'all', label: 'All tracked' },
];

const HARM_LEVELS = [
  { value: '', label: 'Incidents and hazards' },
  { value: 'AI incident', label: 'Incidents only' },
  { value: 'AI hazard', label: 'Hazards only' },
];

const HARM_SERIES = [
  { key: 'AI hazard', label: 'Hazards', swatch: 'viz-1' },
  { key: 'AI incident', label: 'Incidents', swatch: 'viz-2' },
];

/**
 * AI incidents from the OECD AI Incidents Monitor (AIM).
 *
 * AIM records several hundred incidents a month worldwide, so the pipeline asks
 * for three slices rather than all of them: every incident located in
 * Australia, the most-reported ones in the government sector anywhere, and
 * the handful reported most widely overall. This view opens on Australia.
 */
function IncidentsView({ feed, loading, error, since, policyNames }) {
  const [params, setParams] = useSearchParams();
  const [visible, setVisible] = useState(PAGE_SIZE);

  const scope = params.get('scope') || 'australia';
  const harmLevel = params.get('harm') || '';
  const query = params.get('q') || '';

  const update = (key, value, fallback = '') => {
    const next = new URLSearchParams(params);
    if (value && value !== fallback) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setVisible(PAGE_SIZE);
  };

  const incidents = useMemo(() => (feed.items || []).filter((item) => item.kind === 'incident'), [feed.items]);
  const counts = useMemo(
    () => ({
      australia: incidents.filter(isAustralianIncident).length,
      government: incidents.filter(isGovernmentIncident).length,
      all: incidents.length,
    }),
    [incidents]
  );
  const results = useMemo(
    () => filterItems(incidents, { scope, harmLevel, query }),
    [incidents, scope, harmLevel, query]
  );
  const stats = useMemo(
    () => ({
      incidents: results.filter((item) => item.incident?.harm_level === 'AI incident').length,
      hazards: results.filter((item) => item.incident?.harm_level === 'AI hazard').length,
      reports: results.reduce((sum, item) => sum + (item.incident?.articles || 0), 0),
      weekly: weeklySeries(results, { weeks: WEEKS, seriesOf: (item) => item.incident?.harm_level || 'AI incident' }),
    }),
    [results]
  );
  const newCount = results.filter((item) => isNew(item, since)).length;
  const series = HARM_SERIES.filter((s) => !harmLevel || s.key === harmLevel);

  return (
    <div className="page feed-page incidents-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">AI incidents</p>
          <h1>Incidents and hazards</h1>
          <p className="page-sub">
            From the{' '}
            <a href="https://oecd.ai/en/incidents" target="_blank" rel="noopener noreferrer">
              OECD AI Incidents Monitor
            </a>
            , which tracks AI incidents and hazards reported in the world's press
            {feed.generated_at && !loading ? ` · updated ${formatRelative(feed.generated_at)}` : ''}
          </p>
        </div>
      </header>

      {error && (
        <div className="callout callout-info">
          <Icon name="alert" size={18} className="callout-icon" />
          <div className="callout-body">{error}</div>
        </div>
      )}

      <div className="toolbar" role="search">
        <label className="input-with-icon grow">
          <Icon name="search" size={16} />
          <input
            type="search"
            placeholder="Search incidents…"
            value={query}
            onChange={(event) => update('q', event.target.value)}
            aria-label="Search incidents"
          />
        </label>
        <div className="segmented" role="group" aria-label="Where">
          {SCOPES.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={scope === option.value}
              onClick={() => update('scope', option.value, 'australia')}
            >
              {option.label} <span className="segment-count">{counts[option.value]}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="chip-row" role="group" aria-label="Harm level">
        {HARM_LEVELS.map((option) => (
          <button
            key={option.value || 'both'}
            type="button"
            className={`filter-chip${harmLevel === option.value ? ' active' : ''}`}
            aria-pressed={harmLevel === option.value}
            onClick={() => update('harm', option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {!loading && incidents.length > 0 && (
        <section className="incident-summary">
          <div className="stat-tiles">
            <div className="stat-tile">
              <span className="stat-tile-label">Incidents</span>
              <span className="stat-tile-value">{stats.incidents}</span>
              <span className="stat-tile-sub">AI led to actual harm</span>
            </div>
            <div className="stat-tile">
              <span className="stat-tile-label">Hazards</span>
              <span className="stat-tile-value">{stats.hazards}</span>
              <span className="stat-tile-sub">Could plausibly have</span>
            </div>
            <div className="stat-tile">
              <span className="stat-tile-label">Press reports</span>
              <span className="stat-tile-value">{stats.reports.toLocaleString('en-AU')}</span>
              <span className="stat-tile-sub">Linked by the OECD</span>
            </div>
          </div>
          <div className="card chart-card">
            <div className="card-head">
              <div>
                <h2>Per week</h2>
                <p className="card-sub">Records in this view, last {WEEKS} weeks</p>
              </div>
              {series.length > 1 && <Legend items={[...series].reverse()} />}
            </div>
            <StackedColumns
              rows={stats.weekly}
              series={series}
              height={92}
              titleOf={(row) => `Week of ${formatShortDay(new Date(dayTime(row.key)).toISOString())}`}
              tickOf={(row, index) => (index % 2 === 1 ? formatShortDay(new Date(dayTime(row.key)).toISOString()) : null)}
              ariaLabel={`Incidents and hazards per week, last ${WEEKS} weeks`}
            />
          </div>
        </section>
      )}

      <p className="result-count" aria-live="polite">
        {results.length} record{results.length === 1 ? '' : 's'}
        {newCount > 0 && ` · ${newCount} new since your last visit`}
      </p>

      {!loading && results.length === 0 && !error && (
        <div className="empty-state card">
          <span className="empty-icon"><Icon name="search" size={20} /></span>
          <div>
            <strong>No incidents match these filters</strong>
            <p>Try another scope or harm level.</p>
          </div>
        </div>
      )}

      <div className="incident-list card flush">
        {results.slice(0, visible).map((item) => (
          <IncidentCard key={item.id} item={item} since={since} policyNames={policyNames} />
        ))}
      </div>

      {visible < results.length && (
        <button type="button" className="btn btn-secondary btn-block" onClick={() => setVisible((n) => n + PAGE_SIZE)}>
          Show more ({results.length - visible} remaining)
        </button>
      )}

      <aside className="card legend-card">
        <h2>Reading these records</h2>
        <dl className="legend-grid">
          <div>
            <dt><span className="harm-badge harm-incident">Incident</span></dt>
            <dd>An event where an AI system's development or use led to actual harm.</dd>
          </div>
          <div>
            <dt><span className="harm-badge harm-hazard">Hazard</span></dt>
            <dd>An event that could plausibly have led to an incident.</dd>
          </div>
          <div>
            <dt>Reports</dt>
            <dd>How many news articles the OECD has linked to the record — a rough measure of reach.</dd>
          </div>
        </dl>
        <p className="muted">
          The OECD classifies incidents automatically from news coverage, so a record is a starting point, not a
          finding. Follow the link for the articles behind it.
        </p>
      </aside>
    </div>
  );
}

export default IncidentsView;
