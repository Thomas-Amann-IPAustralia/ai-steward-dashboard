import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { formatRelative, HEALTH_LABELS } from '../utils/constants';

const STATUS_LABELS = { ...HEALTH_LABELS, unknown: 'Not checked yet' };

function StatusCell({ status }) {
  return <span className={`status-dot status-${status || 'unknown'}`}>{STATUS_LABELS[status] || status}</span>;
}

const sum = (rows, key) => rows.reduce((total, row) => total + (row?.[key] || 0), 0);

/**
 * Everything the dashboard watches, whether each source is actually being
 * read, and what the filtering did with it.
 *
 * "No changes" is only worth something if the reader can see the source was
 * read, and a badge is only worth something if the reader can see how much
 * was set aside before it. Both are shown here in the open.
 */
function SourcesView({ policySets, health, feed }) {
  const activity = useMemo(() => health?.activity || {}, [health]);
  const days = health?.activity_days || 30;
  const sourcesHealth = health?.sources || {};

  const totals = useMemo(() => {
    const rows = Object.values(activity);
    return {
      checks: sum(rows, 'checks'),
      filtered: sum(rows, 'filtered'),
      rejected: sum(rows, 'rejected'),
      analysed: sum(rows, 'analysed'),
      material: sum(rows, 'material'),
    };
  }, [activity]);

  const sets = [...policySets].sort(
    (a, b) => (a.category || '').localeCompare(b.category || '') || a.setName.localeCompare(b.setName)
  );
  const feeds = Object.entries(feed?.sources || {}).sort(
    ([, a], [, b]) => (a.kind || '').localeCompare(b.kind || '') || (a.category || '').localeCompare(b.category || '')
  );

  return (
    <div className="sources-page">
      <div className="page-header">
        <div>
          <h2>Sources</h2>
          <p className="page-subtitle">What this dashboard watches, and whether each source is being read.</p>
        </div>
      </div>

      {totals.checks > 0 && (
        <section className="filter-evidence" aria-labelledby="filter-evidence-title">
          <h3 id="filter-evidence-title">False changes filtered in the last {days} days</h3>
          <div className="stat-row">
            <div className="stat">
              <span className="stat-value">{totals.checks.toLocaleString('en-AU')}</span>
              <span className="stat-label">document checks</span>
            </div>
            <div className="stat">
              <span className="stat-value">{totals.filtered}</span>
              <span className="stat-label">changes set aside as formatting or a flip-flop</span>
            </div>
            <div className="stat">
              <span className="stat-value">{totals.rejected}</span>
              <span className="stat-label">captures rejected as block or error pages</span>
            </div>
            <div className="stat">
              <span className="stat-value">{totals.analysed}</span>
              <span className="stat-label">changes sent to the AI for analysis</span>
            </div>
            <div className="stat">
              <span className="stat-value">{totals.material}</span>
              <span className="stat-label">judged material and badged</span>
            </div>
          </div>
          <p className="muted">
            A change has to survive every check before it can reach the model or badge a policy:
            the page must look like the document (not an error or block page), its wording — not
            just its typesetting, spacing or links — must differ, and it must not simply be
            returning to a version already seen. The model can still decide nothing material changed.
          </p>
        </section>
      )}

      <section>
        <h3>Policy pages <span className="count-chip">{sets.length}</span></h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Policy set</th>
                <th scope="col">Status</th>
                <th scope="col">Last complete read</th>
                <th scope="col" title={`Checks in the last ${days} days`}>Checks</th>
                <th scope="col" title="Would-be changes set aside as formatting or a flip-flop">Set aside</th>
                <th scope="col" title="Captures rejected as block or error pages">Rejected</th>
                <th scope="col" title="Changes sent to the model">Analysed</th>
              </tr>
            </thead>
            <tbody>
              {sets.map((set) => {
                const source = sourcesHealth[set.setName] || {};
                const counts = activity[set.setName] || {};
                const status = source.status || set.status || 'ok';
                return (
                  <tr key={set.file_id}>
                    <th scope="row">
                      <Link to={`/policy/${set.file_id}`}>{set.setName}</Link>
                      <span className="table-sub">
                        {set.category} · {set.urls.length} document{set.urls.length === 1 ? '' : 's'}
                      </span>
                    </th>
                    <td><StatusCell status={status} /></td>
                    <td>{source.last_success || set.last_success ? formatRelative(source.last_success || set.last_success) : 'Never'}</td>
                    <td>{counts.checks ?? '—'}</td>
                    <td>{counts.filtered ?? '—'}</td>
                    <td>{counts.rejected ?? '—'}</td>
                    <td>{counts.analysed ?? '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3>News and incident feeds <span className="count-chip">{feeds.length}</span></h3>
        {feeds.length === 0 ? (
          <div className="notice-card">The news and incident feed has not run yet.</div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Feed</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last read</th>
                  <th scope="col" title={`Items currently in the ${feed.window_days || 45}-day window`}>Items</th>
                </tr>
              </thead>
              <tbody>
                {feeds.map(([id, source]) => (
                  <tr key={id}>
                    <th scope="row">
                      {source.homepage ? (
                        <a href={source.homepage} target="_blank" rel="noopener noreferrer">{source.name}</a>
                      ) : (
                        source.name
                      )}
                      <span className="table-sub">
                        {source.category}
                        {source.via ? ` · via ${source.via}` : ''}
                      </span>
                      {source.note && <span className="table-note">{source.note}</span>}
                      {source.last_error && source.status !== 'ok' && (
                        <span className="table-error">{source.last_error}</span>
                      )}
                    </th>
                    <td><StatusCell status={source.status} /></td>
                    <td>{source.last_success ? formatRelative(source.last_success) : 'Never'}</td>
                    <td>{source.items}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="muted">
        Want a source added? Policy pages are listed in <code>policy_sets.json</code> and feeds in{' '}
        <code>news_sources.json</code> — suggest one by opening an issue on the project's GitHub.
      </p>
    </div>
  );
}

export default SourcesView;
