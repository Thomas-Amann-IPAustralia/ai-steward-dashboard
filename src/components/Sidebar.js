import React, { useState, useMemo } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { useReviews } from '../hooks/useReviews';
import { formatRelative, primaryUrl, sectorOf, SECTORS, timestampOf } from '../utils/constants';
import { reviewQueue } from '../utils/reviews';
import Icon from './Icon';
import Lettermark from './Lettermark';
import PriorityBadge from './PriorityBadge';
import { HealthPill } from './SourceHealth';

const SORT_OPTIONS = [
  { value: 'name', label: 'Name' },
  { value: 'lastAmended', label: 'Last amended' },
  { value: 'lastChecked', label: 'Last checked' },
  { value: 'health', label: 'Needs attention' },
];

const PRIORITY_FILTERS = ['all', 'critical', 'high', 'medium', 'low'];
const HEALTH_RANK = { failing: 0, degraded: 1, ok: 2 };

/**
 * The list beside an open policy: every monitored set, searchable, sortable
 * and filterable by sector and priority, grouped by category. A set with a change still
 * to review carries a dot, so the queue can be worked through from here.
 */
function Sidebar({ policySets, health, loading, error }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [sortBy, setSortBy] = useState('name');
  const [filterPriority, setFilterPriority] = useState('all');
  const location = useLocation();
  // Opened from a filtered Policy watch, the list starts on the same sector.
  const [searchParams] = useSearchParams();
  const [sector, setSector] = useState(() => searchParams.get('sector') || '');
  const { reviewed } = useReviews();

  const currentFileId = location.pathname.startsWith('/policy/')
    ? decodeURIComponent(location.pathname.split('/policy/')[1])
    : null;

  const pendingIds = useMemo(
    () => new Set(reviewQueue(policySets, reviewed).pending.map((set) => set.file_id)),
    [policySets, reviewed]
  );

  const groupedSets = useMemo(() => {
    const healthSources = health?.sources || {};

    // Timestamps are precomputed once rather than reconstructed inside the
    // comparator on every comparison pass.
    let decorated = policySets.map((set) => ({
      ...set,
      _amended: timestampOf(set.last_amended),
      _checked: timestampOf(set.last_checked),
      _health: healthSources[set.setName]?.status || set.status || 'ok',
    }));

    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      decorated = decorated.filter((set) => set.setName.toLowerCase().includes(term));
    }

    if (sector) {
      decorated = decorated.filter((set) => sectorOf(set) === sector);
    }

    if (filterPriority !== 'all') {
      decorated = decorated.filter((set) => (set.last_priority || '').toLowerCase() === filterPriority);
    }

    decorated.sort((a, b) => {
      if (sortBy === 'lastAmended') return b._amended - a._amended;
      if (sortBy === 'lastChecked') return b._checked - a._checked;
      if (sortBy === 'health') {
        const delta = HEALTH_RANK[a._health] - HEALTH_RANK[b._health];
        if (delta !== 0) return delta;
        return b._amended - a._amended;
      }
      return a.setName.localeCompare(b.setName);
    });

    return {
      list: decorated,
      byCategory: decorated.reduce((acc, set) => {
        const category = set.category || 'Uncategorized';
        if (!acc[category]) acc[category] = [];
        acc[category].push(set);
        return acc;
      }, {}),
    };
  }, [policySets, health, searchTerm, sortBy, filterPriority, sector]);

  return (
    <nav className="list-panel" aria-label="Monitored policies">
      <div className="list-panel-controls">
        <label className="input-with-icon">
          <Icon name="search" size={15} />
          <input
            type="search"
            placeholder="Search policies…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            aria-label="Search policies"
          />
        </label>
        <div className="list-panel-row">
          <label className="select-wrap small">
            <span className="visually-hidden">Sort by</span>
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              {SORT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>Sort: {opt.label}</option>
              ))}
            </select>
            <Icon name="chevron-down" size={13} />
          </label>
        </div>
        <div className="segmented small" role="group" aria-label="Filter by sector">
          {[{ value: '', label: 'All' }, ...SECTORS].map((option) => (
            <button
              key={option.value || 'all'}
              type="button"
              aria-pressed={sector === option.value}
              onClick={() => setSector(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="chip-row tight" role="group" aria-label="Filter by priority">
          {PRIORITY_FILTERS.map((p) => (
            <button
              key={p}
              type="button"
              className={`filter-chip small${filterPriority === p ? ' active' : ''}`}
              onClick={() => setFilterPriority(p)}
              aria-pressed={filterPriority === p}
            >
              {p !== 'all' && <span className={`chip-dot p-${p}`} aria-hidden="true" />}
              {p === 'all' ? 'All' : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="list-panel-body" aria-live="polite">
        {loading && policySets.length === 0 && <div className="skeleton skeleton-list" />}
        {error && <div className="callout callout-critical" role="alert">{error}</div>}
        {!loading && !error && groupedSets.list.length === 0 && (
          <p className="muted list-empty">
            {policySets.length === 0 ? 'No valid policies found to display.' : 'No policies match your search or filters.'}
          </p>
        )}

        {Object.keys(groupedSets.byCategory)
          .sort()
          .map((category) => (
            <div key={category} className="list-group">
              <h2 className="list-group-label">{category}</h2>
              <ul>
                {groupedSets.byCategory[category].map((policySet) => {
                  const active = currentFileId === policySet.file_id;
                  return (
                    <li key={policySet.setName}>
                      <Link
                        to={`/policy/${policySet.file_id}`}
                        className={`list-row${active ? ' active' : ''}`}
                        aria-current={active ? 'page' : undefined}
                      >
                        <Lettermark url={primaryUrl(policySet)} name={policySet.setName} size={28} />
                        <span className="list-row-main">
                          <span className="list-row-title">
                            <span className="list-row-name">{policySet.setName}</span>
                            {pendingIds.has(policySet.file_id) && (
                              <span className="review-dot" title="Change to review">
                                <span className="visually-hidden">Change to review</span>
                              </span>
                            )}
                          </span>
                          <span className="list-row-meta">
                            <PriorityBadge priority={policySet.last_priority} date={policySet.last_amended} />
                            <HealthPill status={policySet._health} />
                            <span className="list-row-time">
                              {policySet.last_amended ? formatRelative(policySet.last_amended) : 'No change'}
                            </span>
                          </span>
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
      </div>
    </nav>
  );
}

export default Sidebar;
