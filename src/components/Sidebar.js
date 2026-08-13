import React, { useState, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { formatDate, formatRelative, primaryUrl, timestampOf } from '../utils/constants';
import Lettermark from './Lettermark';
import PriorityBadge from './PriorityBadge';
import { HealthPill } from './SourceHealth';

const SORT_OPTIONS = [
  { value: 'name', label: 'Name' },
  { value: 'lastAmended', label: 'Last Amended' },
  { value: 'lastChecked', label: 'Last Checked' },
  { value: 'health', label: 'Needs attention' },
];

const PRIORITY_FILTERS = ['all', 'critical', 'high', 'medium', 'low'];
const HEALTH_RANK = { failing: 0, degraded: 1, ok: 2 };

function Sidebar({ policySets, health, loading, error }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [sortBy, setSortBy] = useState('name');
  const [filterPriority, setFilterPriority] = useState('all');
  const navigate = useNavigate();
  const location = useLocation();

  const currentFileId = location.pathname.startsWith('/policy/')
    ? decodeURIComponent(location.pathname.split('/policy/')[1])
    : null;

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

    if (filterPriority !== 'all') {
      decorated = decorated.filter(
        (set) => (set.last_priority || '').toLowerCase() === filterPriority
      );
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
  }, [policySets, health, searchTerm, sortBy, filterPriority]);

  const handleSelect = (policySet) => navigate(`/policy/${policySet.file_id}`);

  return (
    <nav className="sidebar" aria-label="Policy sets navigation">
      <div className="sidebar-controls">
        <input
          type="search"
          className="search-bar"
          placeholder="Search policies..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          aria-label="Search policies"
        />
        <div className="sidebar-control-row">
          <select
            className="sort-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            aria-label="Sort by"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div className="filter-chips" role="group" aria-label="Filter by priority">
          {PRIORITY_FILTERS.map((p) => (
            <button
              key={p}
              type="button"
              className={`filter-chip ${filterPriority === p ? 'active' : ''}`}
              onClick={() => setFilterPriority(p)}
              aria-pressed={filterPriority === p}
            >
              {p === 'all' ? 'All' : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div aria-live="polite">
        {loading && policySets.length === 0 && (
          <div className="loading-message">Loading policies...</div>
        )}
        {error && <div className="error-message" role="alert">{error}</div>}
        {!loading && !error && groupedSets.list.length === 0 && (
          <div className="placeholder sidebar-placeholder">
            {policySets.length === 0
              ? 'No valid policies found to display.'
              : 'No policies match your search or filter.'}
          </div>
        )}
      </div>

      {Object.keys(groupedSets.byCategory).sort().map((category) => (
        <div key={category} className="category-group">
          <h2>{category}</h2>
          <ul>
            {groupedSets.byCategory[category].map((policySet) => (
              <li
                key={policySet.setName}
                className={currentFileId === policySet.file_id ? 'active' : ''}
                onClick={() => handleSelect(policySet)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleSelect(policySet);
                  }
                }}
                tabIndex={0}
                role="button"
                aria-current={currentFileId === policySet.file_id ? 'page' : undefined}
              >
                <div className="page-item">
                  <div className="page-title">
                    <Lettermark url={primaryUrl(policySet)} name={policySet.setName} />
                    <span>{policySet.setName}</span>
                    <PriorityBadge
                      priority={policySet.last_priority}
                      date={policySet.last_amended}
                    />
                    <HealthPill status={policySet._health} />
                  </div>
                  <div className="page-meta">
                    <span>
                      <strong>Last amended:</strong>{' '}
                      {policySet.last_amended ? formatRelative(policySet.last_amended) : 'N/A'}
                    </span>
                    <span>Last checked: {formatDate(policySet.last_checked)}</span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export default Sidebar;
