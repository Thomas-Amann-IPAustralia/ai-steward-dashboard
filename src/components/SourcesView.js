import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { formatRelative, HEALTH_LABELS, primaryUrl, safeHref } from '../utils/constants';
import { DAY_STATUS_LABELS } from '../utils/series';
import Icon from './Icon';
import Lettermark from './Lettermark';
import SourceStrip from './SourceStrip';

const STATUS_LABELS = { ...HEALTH_LABELS, unknown: 'Not checked yet' };

function StatusCell({ status }) {
  return (
    <span className={`status-text status-${status || 'unknown'}`}>
      <span className="status-dot-inline" aria-hidden="true" />
      {STATUS_LABELS[status] || status}
    </span>
  );
}

const sum = (rows, key) => rows.reduce((total, row) => total + (row?.[key] || 0), 0);
const share = (part, whole) => (whole ? Math.max((part / whole) * 100, part ? 0.6 : 0) : 0);
const percent = (part, whole) => {
  if (!whole || !part) return '0%';
  const value = (part / whole) * 100;
  return value < 1 ? '<1%' : `${Math.round(value)}%`;
};

const STRIP_LEGEND = ['ok', 'change', 'material', 'partial', 'failed', 'none'];

/**
 * The filtering, drawn as the funnel it is: every check on the left, what
 * reached the model and what it judged material on the right, and what was
 * stopped on the way. The point it makes is how little gets through.
 */
function FilterFunnel({ totals, days }) {
  const stopped = totals.filtered + totals.rejected;
  const steps = [
    { key: 'checks', value: totals.checks, label: 'Document checks', note: `Every document, every run, last ${days} days` },
    { key: 'analysed', value: totals.analysed, label: 'Sent to the model', note: 'A real change in wording' },
    { key: 'material', value: totals.material, label: 'Judged material', note: 'Badged and put up for review' },
  ];
  return (
    <div className="funnel">
      <ol className="funnel-steps">
        {steps.map((step, index) => (
          <li key={step.key} className={`funnel-step step-${step.key}`}>
            <div className="funnel-step-head">
              <span className="funnel-value">{step.value.toLocaleString('en-AU')}</span>
              {index > 0 && <span className="funnel-share">{percent(step.value, totals.checks)} of checks</span>}
            </div>
            <span className="funnel-label">{step.label}</span>
            <span className="funnel-bar" aria-hidden="true">
              <i style={{ width: `${share(step.value, totals.checks)}%` }} />
            </span>
            <span className="funnel-note">{step.note}</span>
            {index < steps.length - 1 && <Icon name="chevron-right" size={18} className="funnel-arrow" />}
          </li>
        ))}
      </ol>
      <div className="funnel-stopped">
        <span className="funnel-stopped-label">
          <Icon name="x" size={14} />
          Stopped before the model: <strong>{stopped.toLocaleString('en-AU')}</strong>
        </span>
        <span className="tag">{totals.rejected.toLocaleString('en-AU')} captures rejected as block or error pages</span>
        <span className="tag">{totals.filtered.toLocaleString('en-AU')} set aside as formatting or a flip-flop</span>
        <span className="tag">{totals.unchanged.toLocaleString('en-AU')} unchanged</span>
      </div>
    </div>
  );
}

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
  const daily = health?.activity_daily;
  const days = health?.activity_days || 30;
  const sourcesHealth = health?.sources || {};

  const totals = useMemo(() => {
    const rows = Object.values(activity);
    return {
      checks: sum(rows, 'checks'),
      unchanged: sum(rows, 'unchanged'),
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
  const feedsOk = feeds.filter(([, source]) => source.status === 'ok').length;

  return (
    <div className="page sources-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Sources</p>
          <h1>What this dashboard watches</h1>
          <p className="page-sub">Every source, whether it is actually being read, and what the filters did with it.</p>
        </div>
      </header>

      {totals.checks > 0 && (
        <section className="card" aria-labelledby="filter-evidence-title">
          <div className="card-head">
            <div>
              <h2 id="filter-evidence-title">From checks to changes — last {days} days</h2>
              <p className="card-sub">
                A change has to survive every check before it can reach the model or badge a policy: the page must look
                like the document (not an error or block page), its wording — not just its typesetting, spacing or links —
                must differ, and it must not simply be returning to a version already seen. The model can still decide
                nothing material changed.
              </p>
            </div>
          </div>
          <FilterFunnel totals={totals} days={days} />
        </section>
      )}

      <section className="card flush-table" aria-labelledby="policy-sources-title">
        <div className="card-head padded">
          <div>
            <h2 id="policy-sources-title">
              Policy pages <span className="count-pill">{sets.length}</span>
            </h2>
            <p className="card-sub">
              {daily ? `One cell per day for the last ${days} days. Hover a day for what happened.` : 'Read status and the filters’ work per source.'}
            </p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Policy set</th>
                <th scope="col">Status</th>
                {daily && <th scope="col" className="strip-col">Last {days} days</th>}
                <th scope="col">Last complete read</th>
                <th scope="col" className="num" title={`Checks in the last ${days} days`}>Checks</th>
                <th scope="col" className="num" title="Would-be changes set aside as formatting or a flip-flop">Set aside</th>
                <th scope="col" className="num" title="Captures rejected as block or error pages">Rejected</th>
                <th scope="col" className="num" title="Changes sent to the model">Analysed</th>
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
                      <div className="table-source">
                        <Lettermark url={primaryUrl(set)} name={set.setName} size={24} />
                        <div>
                          <Link to={`/policy/${set.file_id}`}>{set.setName}</Link>
                          <span className="table-sub">
                            {set.category} · {set.urls.length} document{set.urls.length === 1 ? '' : 's'}
                          </span>
                        </div>
                      </div>
                    </th>
                    <td><StatusCell status={status} /></td>
                    {daily && (
                      <td className="strip-col">
                        <SourceStrip daily={daily[set.setName]} days={days} label={set.setName} />
                      </td>
                    )}
                    <td>
                      {source.last_success || set.last_success
                        ? formatRelative(source.last_success || set.last_success)
                        : 'Never'}
                    </td>
                    <td className="num">{counts.checks ?? '—'}</td>
                    <td className="num">{counts.filtered ?? '—'}</td>
                    <td className="num">{counts.rejected ?? '—'}</td>
                    <td className="num">{counts.analysed ?? '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {daily && (
          <ul className="chart-legend padded">
            {STRIP_LEGEND.map((status) => (
              <li key={status}>
                <span className={`legend-key status-${status}`} aria-hidden="true" />
                {DAY_STATUS_LABELS[status]}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card flush-table" aria-labelledby="feeds-title">
        <div className="card-head padded">
          <div>
            <h2 id="feeds-title">
              News and incident feeds <span className="count-pill">{feeds.length}</span>
            </h2>
            <p className="card-sub">
              {feeds.length ? `${feedsOk} of ${feeds.length} read successfully on the last run.` : 'Not run yet.'}
            </p>
          </div>
        </div>
        {feeds.length === 0 ? (
          <p className="muted padded">The news and incident feed has not run yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Feed</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last read</th>
                  <th scope="col" className="num" title={`Items currently in the ${feed.window_days || 45}-day window`}>Items</th>
                </tr>
              </thead>
              <tbody>
                {feeds.map(([id, source]) => (
                  <tr key={id}>
                    <th scope="row">
                      {source.homepage ? (
                        <a href={safeHref(source.homepage)} target="_blank" rel="noopener noreferrer">{source.name}</a>
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
                    <td className="num">{source.items}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="muted footnote">
        Want a source added? Policy pages are listed in <code>policy_sets.json</code> and feeds in{' '}
        <code>news_sources.json</code> — suggest one by opening an issue on the project's GitHub.
      </p>
    </div>
  );
}

export default SourcesView;
