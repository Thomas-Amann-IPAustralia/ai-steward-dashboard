import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { usePolicyDetail } from '../hooks/usePolicyDetail';
import { useHistory } from '../hooks/useHistory';
import { useReviews } from '../hooks/useReviews';
import { useToast } from '../hooks/useToast';
import {
  DOCUMENT_STATES,
  formatDate,
  formatDay,
  formatRelative,
  HEALTH_LABELS,
  hostOf,
  primaryUrl,
  REPO_URL,
  safeHref,
  timestampOf,
  VERDICT_LABELS,
} from '../utils/constants';
import { formatAgo, itemsForPolicy } from '../utils/news';
import { hasMaterialChange, isReviewed, REVIEW_WINDOW_DAYS } from '../utils/reviews';
import DiffView from './DiffView';
import { FeedCard } from './FeedCards';
import HistoryTimeline from './HistoryTimeline';
import Icon from './Icon';
import Lettermark from './Lettermark';
import SourceStrip from './SourceStrip';
import PriorityBadge from './PriorityBadge';
import SafeMarkdown from './SafeMarkdown';
import { SourceHealthNotice } from './SourceHealth';

const DAY_MS = 24 * 60 * 60 * 1000;

const feedbackUrl = (setName, fileId, verdict, judgement) => {
  const title = `Analysis feedback (${judgement}): ${setName}`;
  const body = [
    `**Policy set:** ${setName}`,
    `**Detail page:** ${window.location.href}`,
    `**Verdict recorded:** ${verdict || 'n/a'}`,
    `**Judgement:** ${judgement === 'up' ? '👍 useful' : '👎 not useful'}`,
    '',
    '**Why?** (optional — a sentence is plenty)',
    '',
  ].join('\n');
  return `${REPO_URL}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}&labels=analysis-feedback`;
};

/** What the gates did with this source's checks, as a left-to-right flow. */
function ActivityFlow({ counts, days }) {
  if (!counts || !counts.checks) return null;
  const steps = [
    { label: 'document checks', value: counts.checks },
    { label: 'set aside as formatting or a flip-flop', value: counts.filtered || 0 },
    { label: 'bad captures rejected', value: counts.rejected || 0 },
    { label: 'sent for analysis', value: counts.analysed || 0 },
    { label: 'judged material', value: counts.material || 0, strong: true },
  ];
  return (
    <ol className="activity-flow" aria-label={`Last ${days} days`}>
      {steps.map((step) => (
        <li key={step.label} className={step.strong ? 'strong' : ''}>
          <strong>{step.value.toLocaleString('en-AU')}</strong>
          <span>{step.label}</span>
        </li>
      ))}
    </ol>
  );
}

const RELATED_LIMIT = 6;

function PolicyDetail({ policySets, health, feed, since }) {
  const { fileId } = useParams();
  const { analysis, diff, snapshot, loading, error } = usePolicyDetail(fileId);
  const historyState = useHistory(fileId);
  const { reviewed, markReviewed } = useReviews();
  const toast = useToast();

  const policySet = policySets.find((p) => p.file_id === fileId);
  const sourceHealth = policySet ? health?.sources?.[policySet.setName] : null;
  const related = itemsForPolicy(feed?.items, fileId);
  const policyNames = Object.fromEntries(policySets.map((set) => [set.file_id, set.setName]));

  if (loading || (!policySet && policySets.length === 0)) {
    return (
      <div className="page detail-page" role="status" aria-live="polite">
        <span className="visually-hidden">Loading page data…</span>
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-hero" />
        <div className="skeleton skeleton-block" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="page detail-page">
        <div className="callout callout-critical" role="alert" aria-live="assertive">
          <Icon name="alert" size={18} className="callout-icon" />
          <div className="callout-body">{error}</div>
        </div>
      </div>
    );
  }

  if (!policySet) {
    return (
      <div className="page detail-page">
        <div className="empty-state card">
          <span className="empty-icon"><Icon name="policy" size={20} /></span>
          <div>
            <strong>Policy not found</strong>
            <p>The selected policy could not be found. Choose one from the list of monitored policies.</p>
          </div>
        </div>
      </div>
    );
  }

  const documents = policySet.documents || {};
  const changedDocuments = analysis?.changed_documents || [];
  const verdict = analysis?.verdict;
  const review = policySet.last_review;
  const declined = ['no_material_change', 'rebaselined', 'reverted'].includes(review?.verdict);
  const status = sourceHealth?.status || policySet.status || 'ok';
  const reviewable =
    hasMaterialChange(policySet) && timestampOf(policySet.last_amended) > Date.now() - REVIEW_WINDOW_DAYS * DAY_MS;
  const done = isReviewed(reviewed, policySet);
  const host = hostOf(primaryUrl(policySet));
  const counts = health?.activity?.[policySet.setName];
  const days = health?.activity_days || 30;
  const daily = health?.activity_daily?.[policySet.setName];

  const toggleReviewed = () => {
    markReviewed(policySet, !done);
    if (!done) {
      toast(`Marked “${policySet.setName}” as reviewed`, {
        action: 'Undo',
        onAction: () => markReviewed(policySet, false),
      });
    }
  };

  return (
    <div className="page detail-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/policies">Policy watch</Link>
        <Icon name="chevron-right" size={14} />
        <span aria-current="page">{policySet.setName}</span>
      </nav>

      <header className="detail-head">
        <Lettermark url={primaryUrl(policySet)} name={policySet.setName} size={48} />
        <div className="detail-title">
          <h1>{policySet.setName}</h1>
          <p className="page-sub">
            {policySet.category} · {policySet.urls.length} document{policySet.urls.length === 1 ? '' : 's'}
            {host && (
              <>
                {' · '}
                <a href={safeHref(primaryUrl(policySet))} target="_blank" rel="noopener noreferrer" className="subtle-link">
                  {host} <Icon name="external" size={12} />
                </a>
              </>
            )}
          </p>
        </div>
        {reviewable && (
          <div className="page-actions">
            <button
              type="button"
              className={`btn ${done ? 'btn-secondary is-done' : 'btn-primary'}`}
              onClick={toggleReviewed}
              aria-pressed={done}
            >
              <Icon name={done ? 'check-circle' : 'check'} size={16} />
              {done ? 'Reviewed' : 'Mark reviewed'}
            </button>
          </div>
        )}
      </header>

      <dl className="stat-strip">
        <div>
          <dt>Last checked</dt>
          <dd title={formatDate(policySet.last_checked)}>{formatAgo(policySet.last_checked) || 'Never'}</dd>
        </div>
        <div>
          <dt>Last material change</dt>
          <dd title={formatDate(policySet.last_amended)}>
            {policySet.last_amended ? formatRelative(policySet.last_amended) : 'None recorded'}
          </dd>
        </div>
        <div>
          <dt>Latest priority</dt>
          <dd>
            {policySet.last_priority ? <PriorityBadge priority={policySet.last_priority} date={policySet.last_amended} /> : '—'}
          </dd>
        </div>
        <div>
          <dt>Source status</dt>
          <dd>
            <span className={`status-text status-${status}`}>
              <span className="status-dot-inline" aria-hidden="true" />
              {HEALTH_LABELS[status] || status}
            </span>
          </dd>
        </div>
      </dl>

      <SourceHealthNotice source={sourceHealth} />

      {(counts?.checks > 0 || daily) && (
        <section className="card" aria-labelledby="activity-title">
          <div className="card-head">
            <div>
              <h2 id="activity-title">Last {days} days</h2>
              <p className="card-sub">Every check of this source, and what the filters did with it.</p>
            </div>
          </div>
          {daily && <SourceStrip daily={daily} days={days} label={policySet.setName} />}
          <ActivityFlow counts={counts} days={days} />
        </section>
      )}

      {declined && (
        <div className="callout callout-info" role="status">
          <Icon name="eye" size={18} className="callout-icon" />
          <div className="callout-body">
            <strong>Reviewed {formatDate(review.timestamp)}: {VERDICT_LABELS[review.verdict] || review.verdict}.</strong>{' '}
            {review.summary}
            <p>The set was not badged and its last-amended date was not moved. The analysis below is the most recent material change.</p>
          </div>
        </div>
      )}

      {analysis && (
        <section className="card analysis-card" aria-labelledby="analysis-title">
          <div className="card-head">
            <div>
              <h2 id="analysis-title">
                <Icon name="sparkle" size={16} /> Analysis
              </h2>
              <p className="card-sub">{formatDate(analysis.date_time)}</p>
            </div>
            <div className="analysis-meta">
              <PriorityBadge priority={analysis.priority} solid />
              {verdict && VERDICT_LABELS[verdict] && <span className="verdict-chip">{VERDICT_LABELS[verdict]}</span>}
            </div>
          </div>

          <p className="analysis-summary">{analysis.summary}</p>

          {changedDocuments.length > 0 && (
            <p className="changed-documents-line">
              <Icon name="file" size={14} />
              <span>
                <strong>Changed:</strong> {changedDocuments.join(', ')}.{' '}
                {policySet.urls.length > changedDocuments.length && (
                  <>
                    The other {policySet.urls.length - changedDocuments.length} document
                    {policySet.urls.length - changedDocuments.length === 1 ? '' : 's'} in this set were checked and are
                    unchanged.
                  </>
                )}
              </span>
            </p>
          )}

          {analysis.fingerprint?.length > 0 && (
            <div className="fingerprint-tags" aria-label="Watchlist terms in this change">
              {analysis.fingerprint.map((tag) => (
                <span className="tag" key={tag}>{tag.replace('watchlist:', '')}</span>
              ))}
            </div>
          )}

          <details className="analysis-details" open>
            <summary>
              <Icon name="chevron-right" size={14} className="disclosure-chevron" />
              Detailed analysis
            </summary>
            <div className="analysis-content prose">
              <SafeMarkdown>{analysis.analysis}</SafeMarkdown>
            </div>
          </details>

          <div className="feedback-row">
            <span>Was this analysis useful?</span>
            <a className="btn btn-ghost btn-sm" href={feedbackUrl(policySet.setName, fileId, verdict, 'up')} target="_blank" rel="noopener noreferrer">
              <Icon name="thumbs-up" size={15} /> Yes
            </a>
            <a className="btn btn-ghost btn-sm" href={feedbackUrl(policySet.setName, fileId, verdict, 'down')} target="_blank" rel="noopener noreferrer">
              <Icon name="thumbs-down" size={15} /> No
            </a>
          </div>
        </section>
      )}

      <section className="card" aria-labelledby="diff-title">
        <div className="card-head">
          <div>
            <h2 id="diff-title">What changed</h2>
            <p className="card-sub">Changed wording is highlighted word by word.</p>
          </div>
        </div>
        <DiffView diff={diff} changedDocuments={changedDocuments} />
      </section>

      <section className="card" aria-labelledby="documents-title">
        <div className="card-head">
          <div>
            <h2 id="documents-title">Documents in this set</h2>
            <p className="card-sub">Each document is read and compared on its own.</p>
          </div>
        </div>
        <ul className="document-list">
          {policySet.urls.map((urlObj) => {
            const record = documents[urlObj.url] || {};
            const label = record.label || urlObj.url;
            const changed = changedDocuments.includes(label);
            const state = changed ? 'changed' : record.status || 'unknown';

            return (
              <li key={urlObj.url} className="document-item">
                <Icon name="file" size={16} className="document-icon" />
                <div className="document-main">
                  <span className="document-label">{label}</span>
                  <a href={safeHref(urlObj.url)} target="_blank" rel="noopener noreferrer" className="document-url">
                    {urlObj.url}
                  </a>
                  {record.last_error && <span className="document-error">{record.last_error}</span>}
                  {record.route === 'archive' && record.archived_at && (
                    <span className="document-note">
                      The site refused every direct read, so this was read from the Internet Archive's copy of{' '}
                      {formatDay(record.archived_at)}.
                    </span>
                  )}
                </div>
                <span className={`document-state state-${state}`}>
                  {DOCUMENT_STATES[state] || state.replace(/_/g, ' ')}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      {related.length > 0 && (
        <section className="card" aria-labelledby="related-title">
          <div className="card-head">
            <div>
              <h2 id="related-title">Related news and incidents</h2>
              <p className="card-sub">Items from the news and incident feeds that name this provider or agency.</p>
            </div>
            {related.length > RELATED_LIMIT && (
              <Link to="/news?related=1&show=all" className="card-link">
                {related.length - RELATED_LIMIT} more <Icon name="arrow-right" size={14} />
              </Link>
            )}
          </div>
          <div className="compact-feed">
            {related.slice(0, RELATED_LIMIT).map((item) => (
              <FeedCard key={item.id} item={item} since={since} policyNames={policyNames} compact />
            ))}
          </div>
        </section>
      )}

      <section className="card" aria-labelledby="history-title">
        <div className="card-head">
          <div>
            <h2 id="history-title">Change history</h2>
            <p className="card-sub">Every archived analysis for this set. Open one to read it in full.</p>
          </div>
        </div>
        <HistoryTimeline entries={historyState.entries} loading={historyState.loading} error={historyState.error} />
      </section>

      <details className="card snapshot-disclosure">
        <summary>
          <Icon name="chevron-right" size={14} className="disclosure-chevron" />
          Full captured text <span className="muted">({Math.round((snapshot?.length || 0) / 1024)} kB)</span>
        </summary>
        <pre className="snapshot-content">{snapshot}</pre>
      </details>
    </div>
  );
}

export default PolicyDetail;
