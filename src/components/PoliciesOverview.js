import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useHistoryIndex } from '../hooks/useHistory';
import { useLatestAnalyses } from '../hooks/useLatestAnalyses';
import { useReviews } from '../hooks/useReviews';
import {
  changeSummaryOf,
  formatRelative,
  hostOf,
  PRIORITY_DESCRIPTIONS,
  PRIORITY_ORDER,
  primaryUrl,
  timestampOf,
} from '../utils/constants';
import { isReviewed, reviewQueue } from '../utils/reviews';
import ChangeTimeline from './ChangeTimeline';
import Icon from './Icon';
import Lettermark from './Lettermark';
import PriorityBadge from './PriorityBadge';
import { HealthPill } from './SourceHealth';
import SourceStrip from './SourceStrip';

const RANGES = [
  { value: 91, label: '3M' },
  { value: 182, label: '6M' },
  { value: 365, label: '1Y' },
];

const SORTS = [
  { value: 'recent', label: 'Recently changed' },
  { value: 'name', label: 'Name' },
  { value: 'health', label: 'Needs attention' },
];

const HEALTH_RANK = { failing: 0, degraded: 1, ok: 2 };

/**
 * Every monitored policy set: when each one changes, on a shared timeline,
 * and a card per set saying where it stands — its last change, whether that
 * is still waiting for review, and whether the source is being read at all.
 */
function PoliciesOverview({ policySets, health, loading }) {
  const [params, setParams] = useSearchParams();
  const [range, setRange] = useState(182);
  const history = useHistoryIndex();
  const { reviewed } = useReviews();
  const analyses = useLatestAnalyses(policySets.map((set) => set.file_id));

  const query = params.get('q') || '';
  const priority = params.get('priority') || '';
  const sort = params.get('sort') || 'recent';

  const update = (key, value, fallback = '') => {
    const next = new URLSearchParams(params);
    if (value && value !== fallback) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const healthSources = useMemo(() => health?.sources || {}, [health]);
  const daily = health?.activity_daily;
  const pendingIds = useMemo(
    () => new Set(reviewQueue(policySets, reviewed).pending.map((set) => set.file_id)),
    [policySets, reviewed]
  );

  const sets = useMemo(() => {
    const term = query.toLowerCase();
    return policySets
      .map((set) => ({ ...set, _health: healthSources[set.setName]?.status || set.status || 'ok' }))
      .filter((set) => !term || `${set.setName} ${set.category} ${primaryUrl(set)}`.toLowerCase().includes(term))
      .filter((set) => !priority || (set.last_priority || '').toLowerCase() === priority)
      .sort((a, b) => {
        if (sort === 'name') return a.setName.localeCompare(b.setName);
        if (sort === 'health') {
          return HEALTH_RANK[a._health] - HEALTH_RANK[b._health] || timestampOf(b.last_amended) - timestampOf(a.last_amended);
        }
        return timestampOf(b.last_amended) - timestampOf(a.last_amended);
      });
  }, [policySets, healthSources, query, priority, sort]);

  return (
    <div className="page policies-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Policy watch</p>
          <h1>Monitored policies</h1>
          <p className="page-sub">
            {policySets.length} policy sets — government AI policy and the terms of AI services APS staff use —
            checked every day for changes in wording.
          </p>
        </div>
        {pendingIds.size > 0 && (
          <div className="page-actions">
            <span className="count-banner">
              <Icon name="inbox" size={16} />
              {pendingIds.size} change{pendingIds.size === 1 ? '' : 's'} to review
            </span>
          </div>
        )}
      </header>

      <section className="card" aria-labelledby="timeline-title">
        <div className="card-head">
          <div>
            <h2 id="timeline-title">When each source changed</h2>
            <p className="card-sub">
              One lane per source. Solid dots were judged material, coloured by priority; hollow ones were analysed
              and let pass. Hover a dot for the summary.
            </p>
          </div>
          <div className="segmented small" role="group" aria-label="Time range">
            {RANGES.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={range === option.value}
                onClick={() => setRange(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        {history.error ? (
          <p className="muted">{history.error}</p>
        ) : (
          <ChangeTimeline policySets={policySets} entries={history.entries} days={range} />
        )}
      </section>

      <div className="toolbar" role="search">
        <label className="input-with-icon grow">
          <Icon name="search" size={16} />
          <input
            type="search"
            placeholder="Filter policies…"
            value={query}
            onChange={(event) => update('q', event.target.value)}
            aria-label="Filter policies"
          />
        </label>
        <div className="chip-row" role="group" aria-label="Latest priority">
          {['', ...PRIORITY_ORDER].map((value) => (
            <button
              key={value || 'all'}
              type="button"
              className={`filter-chip${priority === value ? ' active' : ''}`}
              aria-pressed={priority === value}
              onClick={() => update('priority', value)}
            >
              {value && <span className={`chip-dot p-${value}`} aria-hidden="true" />}
              {value ? value.charAt(0).toUpperCase() + value.slice(1) : 'Any priority'}
            </button>
          ))}
        </div>
        <label className="select-wrap">
          <span className="visually-hidden">Sort by</span>
          <select value={sort} onChange={(event) => update('sort', event.target.value, 'recent')}>
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          <Icon name="chevron-down" size={14} />
        </label>
      </div>

      {loading && policySets.length === 0 && (
        <div className="policy-grid">
          {[0, 1, 2, 3].map((i) => <div className="skeleton skeleton-card" key={i} />)}
        </div>
      )}
      {!loading && sets.length === 0 && (
        <div className="empty-state card">
          <span className="empty-icon"><Icon name="search" size={20} /></span>
          <div>
            <strong>No policies match</strong>
            <p>Try a different search or priority.</p>
          </div>
        </div>
      )}

      <ul className="policy-grid">
        {sets.map((set) => {
          const summary = changeSummaryOf(set, analyses[set.file_id]);
          const pending = pendingIds.has(set.file_id);
          const done = !pending && isReviewed(reviewed, set);
          return (
            <li key={set.file_id}>
              <Link className={`policy-card${pending ? ' pending' : ''}`} to={`/policy/${set.file_id}`}>
                <div className="policy-card-head">
                  <Lettermark url={primaryUrl(set)} name={set.setName} size={36} />
                  <div className="policy-card-title">
                    <h3>{set.setName}</h3>
                    <span>
                      {set.category} · {hostOf(primaryUrl(set))}
                    </span>
                  </div>
                  <HealthPill status={set._health} />
                </div>
                <p className={`policy-card-summary${summary ? '' : ' muted'}`}>
                  {summary || (set.last_amended ? 'No summary recorded for the last change.' : 'No change recorded yet.')}
                </p>
                {daily && <SourceStrip daily={daily[set.setName]} label={set.setName} />}
                <div className="policy-card-foot">
                  <PriorityBadge priority={set.last_priority} date={set.last_amended} kind={set.kind} />
                  <span className="foot-meta">
                    {set.last_amended ? `Changed ${formatRelative(set.last_amended)}` : 'Never changed'}
                  </span>
                  <span className="foot-meta">
                    {set.urls.length} doc{set.urls.length === 1 ? '' : 's'}
                  </span>
                  {pending && <span className="review-chip">To review</span>}
                  {done && (
                    <span className="review-chip done">
                      <Icon name="check" size={12} /> Reviewed
                    </span>
                  )}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>

      <aside className="card legend-card">
        <h2>What the priorities mean</h2>
        <dl className="legend-grid">
          {PRIORITY_ORDER.map((level) => (
            <div key={level}>
              <dt><PriorityBadge priority={level} solid /></dt>
              <dd>{PRIORITY_DESCRIPTIONS[level]}</dd>
            </div>
          ))}
        </dl>
        <p className="muted">
          A priority describes a change, not the document, and it fades after 30 days. A change that turns out to be
          only formatting, or a page flipping between two versions, is filtered out before it can be rated at all.
        </p>
      </aside>
    </div>
  );
}

export default PoliciesOverview;
