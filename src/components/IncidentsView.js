import React, { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { formatRelative } from '../utils/constants';
import { filterItems, isAustralianIncident, isGovernmentIncident, isNew } from '../utils/news';
import { IncidentCard } from './FeedCards';

const PAGE_SIZE = 30;

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
  const newCount = results.filter((item) => isNew(item, since)).length;

  return (
    <div className="feed-page">
      <div className="page-header">
        <div>
          <h2>AI incidents</h2>
          <p className="page-subtitle">
            From the{' '}
            <a href="https://oecd.ai/en/incidents" target="_blank" rel="noopener noreferrer">
              OECD AI Incidents Monitor
            </a>
            , which tracks AI incidents and hazards reported in the world's press
            {feed.generated_at && !loading ? ` · updated ${formatRelative(feed.generated_at)}` : ''}
          </p>
        </div>
      </div>

      {error && <div className="notice-card">{error}</div>}

      <div className="filter-bar" role="search">
        <input
          type="search"
          className="search-bar"
          placeholder="Search incidents…"
          value={query}
          onChange={(event) => update('q', event.target.value)}
          aria-label="Search incidents"
        />
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
        <div className="filter-chips" role="group" aria-label="Harm level">
          {HARM_LEVELS.map((option) => (
            <button
              key={option.value || 'both'}
              type="button"
              className={`filter-chip ${harmLevel === option.value ? 'active' : ''}`}
              aria-pressed={harmLevel === option.value}
              onClick={() => update('harm', option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <p className="result-count" aria-live="polite">
        {results.length} record{results.length === 1 ? '' : 's'}
        {newCount > 0 && ` · ${newCount} new since your last visit`}
      </p>

      {!loading && results.length === 0 && !error && (
        <div className="notice-card">No incidents match these filters.</div>
      )}

      <div className="feed-list">
        {results.slice(0, visible).map((item) => (
          <IncidentCard key={item.id} item={item} since={since} policyNames={policyNames} />
        ))}
      </div>

      {visible < results.length && (
        <button type="button" className="secondary-button" onClick={() => setVisible((n) => n + PAGE_SIZE)}>
          Show more ({results.length - visible} remaining)
        </button>
      )}

      <aside className="legend">
        <h3>Reading these records</h3>
        <dl>
          <dt>Incident</dt>
          <dd>An event where an AI system's development or use led to actual harm.</dd>
          <dt>Hazard</dt>
          <dd>An event that could plausibly have led to an incident.</dd>
          <dt>Reports</dt>
          <dd>How many news articles the OECD has linked to the record — a rough measure of reach.</dd>
        </dl>
        <p>
          The OECD classifies incidents automatically from news coverage, so a record is a
          starting point, not a finding. Follow the link for the articles behind it.
        </p>
      </aside>
    </div>
  );
}

export default IncidentsView;
