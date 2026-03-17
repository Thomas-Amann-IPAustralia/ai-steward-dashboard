import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatDate, getPriorityColor } from '../utils/constants';

function DashboardHome({ policySets }) {
  const navigate = useNavigate();

  const stats = useMemo(() => {
    const total = policySets.length;
    const withChanges = policySets.filter(p => p.last_amended && p.last_amended !== p.last_checked);

    const now = new Date();
    const sevenDaysAgo = new Date(now - 7 * 24 * 60 * 60 * 1000);
    const recentChanges = policySets
      .filter(p => p.last_amended && new Date(p.last_amended) > sevenDaysAgo)
      .sort((a, b) => new Date(b.last_amended) - new Date(a.last_amended));

    const lastScan = policySets.reduce((latest, p) => {
      const checked = new Date(p.last_checked || 0);
      return checked > latest ? checked : latest;
    }, new Date(0));

    const priorityCounts = policySets.reduce((acc, p) => {
      const priority = (p.last_priority || '').toLowerCase();
      if (priority) acc[priority] = (acc[priority] || 0) + 1;
      return acc;
    }, {});

    return { total, withChanges: withChanges.length, recentChanges, lastScan, priorityCounts };
  }, [policySets]);

  return (
    <div className="dashboard-home">
      <h2>Dashboard Overview</h2>

      <div className="stat-cards">
        <div className="stat-card">
          <div className="stat-number">{stats.total}</div>
          <div className="stat-label">Policies Monitored</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{stats.recentChanges.length}</div>
          <div className="stat-label">Changes (Last 7 Days)</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{formatDate(stats.lastScan.toISOString())}</div>
          <div className="stat-label">Last Scan</div>
        </div>
        {Object.keys(stats.priorityCounts).length > 0 && (
          <div className="stat-card">
            <div className="priority-breakdown">
              {Object.entries(stats.priorityCounts).map(([priority, count]) => (
                <span key={priority} className="priority-count" style={{ color: getPriorityColor(priority) }}>
                  {count} {priority}
                </span>
              ))}
            </div>
            <div className="stat-label">By Priority</div>
          </div>
        )}
      </div>

      {stats.recentChanges.length > 0 ? (
        <div className="recent-changes">
          <h3>Recent Changes</h3>
          <ul>
            {stats.recentChanges.map(p => (
              <li
                key={p.file_id}
                className="recent-change-item"
                onClick={() => navigate(`/policy/${p.file_id}`)}
                onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/policy/${p.file_id}`); }}
                tabIndex={0}
                role="button"
              >
                <div className="recent-change-name">
                  <img
                    src={`https://www.google.com/s2/favicons?sz=16&domain_url=${p.urls[0].url}`}
                    alt=""
                    className="favicon"
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                  <span>{p.setName}</span>
                  {p.last_priority && (
                    <span
                      className="priority-badge"
                      style={{ backgroundColor: getPriorityColor(p.last_priority) }}
                    >
                      {p.last_priority.toUpperCase()}
                    </span>
                  )}
                </div>
                <span className="recent-change-date">
                  Changed: {formatDate(p.last_amended)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="recent-changes">
          <h3>Recent Changes</h3>
          <p>No changes detected in the last 7 days. All monitored policies are stable.</p>
        </div>
      )}
    </div>
  );
}

export default DashboardHome;
