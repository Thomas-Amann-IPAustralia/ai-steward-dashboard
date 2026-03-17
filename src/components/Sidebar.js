import React, { useState, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { formatDate } from '../utils/constants';

const SORT_OPTIONS = [
  { value: 'name', label: 'Name' },
  { value: 'lastAmended', label: 'Last Amended' },
  { value: 'lastChecked', label: 'Last Checked' },
];

const PRIORITY_FILTERS = ['all', 'critical', 'high', 'medium', 'low'];

function Sidebar({ policySets, loading, error }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [sortBy, setSortBy] = useState('name');
  const [filterPriority, setFilterPriority] = useState('all');
  const navigate = useNavigate();
  const location = useLocation();

  const currentFileId = location.pathname.startsWith('/policy/')
    ? decodeURIComponent(location.pathname.split('/policy/')[1])
    : null;

  const filteredAndSorted = useMemo(() => {
    let filtered = policySets;

    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      filtered = filtered.filter(p => p.setName.toLowerCase().includes(term));
    }

    if (filterPriority !== 'all') {
      filtered = filtered.filter(p =>
        (p.last_priority || '').toLowerCase() === filterPriority
      );
    }

    const sorted = [...filtered].sort((a, b) => {
      if (sortBy === 'lastAmended') {
        return new Date(b.last_amended || 0) - new Date(a.last_amended || 0);
      }
      if (sortBy === 'lastChecked') {
        return new Date(b.last_checked || 0) - new Date(a.last_checked || 0);
      }
      return a.setName.localeCompare(b.setName);
    });

    return sorted;
  }, [policySets, searchTerm, sortBy, filterPriority]);

  const groupedSets = useMemo(() => {
    return filteredAndSorted.reduce((acc, set) => {
      const category = set.category || 'Uncategorized';
      if (!acc[category]) acc[category] = [];
      acc[category].push(set);
      return acc;
    }, {});
  }, [filteredAndSorted]);

  const handleSelect = (policySet) => {
    navigate(`/policy/${policySet.file_id}`);
  };

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
            {SORT_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div className="filter-chips" role="group" aria-label="Filter by priority">
          {PRIORITY_FILTERS.map(p => (
            <button
              key={p}
              className={`filter-chip ${filterPriority === p ? 'active' : ''}`}
              onClick={() => setFilterPriority(p)}
            >
              {p === 'all' ? 'All' : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading && policySets.length === 0 && <div className="loading-message">Loading policies...</div>}
      {error && <div className="error-message">{error}</div>}

      {!loading && !error && filteredAndSorted.length === 0 && (
        <div className="placeholder sidebar-placeholder">
          {policySets.length === 0
            ? 'No valid policies found to display.'
            : 'No policies match your search or filter.'}
        </div>
      )}

      {Object.keys(groupedSets).sort().map(category => (
        <div key={category} className="category-group">
          <h2>{category}</h2>
          <ul>
            {groupedSets[category].map(policySet => (
              <li
                key={policySet.setName}
                className={currentFileId === policySet.file_id ? 'active' : ''}
                onClick={() => handleSelect(policySet)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleSelect(policySet); } }}
                tabIndex={0}
                role="button"
                aria-current={currentFileId === policySet.file_id ? 'page' : undefined}
              >
                <div className="page-item">
                  <div className="page-title">
                    <img
                      src={`https://www.google.com/s2/favicons?sz=16&domain_url=${policySet.urls[0].url}`}
                      alt=""
                      className="favicon"
                      onError={(e) => { e.target.style.display = 'none'; }}
                    />
                    <span>{policySet.setName}</span>
                    {policySet.last_priority && (
                      <span className={`sidebar-priority priority-${policySet.last_priority.toLowerCase()}`}>
                        {policySet.last_priority.toUpperCase()}
                      </span>
                    )}
                  </div>
                  <div className="page-meta">
                    <span><strong>Last amended:</strong> {policySet.last_amended ? formatDate(policySet.last_amended) : 'N/A'}</span>
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
