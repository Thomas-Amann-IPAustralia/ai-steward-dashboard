import React from 'react';
import { useParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { usePolicyDetail } from '../hooks/usePolicyDetail';
import { useHistory } from '../hooks/useHistory';
import {
  formatDate,
  formatRelative,
  REPO_URL,
  VERDICT_LABELS,
} from '../utils/constants';
import DiffView from './DiffView';
import HistoryTimeline from './HistoryTimeline';
import PriorityBadge from './PriorityBadge';
import { SourceHealthNotice } from './SourceHealth';

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

function PolicyDetail({ policySets, health }) {
  const { fileId } = useParams();
  const { analysis, diff, snapshot, loading, error } = usePolicyDetail(fileId);
  const historyState = useHistory(fileId);

  const policySet = policySets.find((p) => p.file_id === fileId);
  const sourceHealth = policySet ? health?.sources?.[policySet.setName] : null;

  if (loading) {
    return (
      <div className="loading-message" role="status" aria-live="polite">
        Loading page data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-message" role="alert" aria-live="assertive">
        {error}
      </div>
    );
  }

  if (!policySet) {
    return (
      <div className="placeholder">
        <h2>Policy Not Found</h2>
        <p>The selected policy could not be found. Please select a policy from the sidebar.</p>
      </div>
    );
  }

  const documents = policySet.documents || {};
  const changedDocuments = analysis?.changed_documents || [];
  const verdict = analysis?.verdict;
  const review = policySet.last_review;
  const declined = review?.verdict === 'no_material_change' || review?.verdict === 'rebaselined';

  return (
    <div className="policy-detail">
      <div className="content-header">
        <h2>{policySet.setName}</h2>
        <p className="detail-subtitle">
          Last checked {formatDate(policySet.last_checked)}
          {policySet.last_amended && ` · last change ${formatRelative(policySet.last_amended)}`}
        </p>
      </div>

      <SourceHealthNotice source={sourceHealth} />

      {/* Which document in the set moved. The steward used to get a set-level
          badge and had to go looking. */}
      <section className="document-status">
        <h3>Documents in this set</h3>
        <ul className="document-list">
          {policySet.urls.map((urlObj) => {
            const record = documents[urlObj.url] || {};
            const label = record.label || urlObj.url;
            const changed = changedDocuments.includes(label);
            const state = record.status || 'unknown';

            return (
              <li key={urlObj.url} className={`document-item state-${state}`}>
                <div className="document-item-head">
                  <span className="document-label">{label}</span>
                  <span className={`document-state state-${state}`}>
                    {changed ? 'changed' : state.replace(/_/g, ' ')}
                  </span>
                </div>
                <a href={urlObj.url} target="_blank" rel="noopener noreferrer" className="document-url">
                  {urlObj.url}
                </a>
                {record.last_error && (
                  <span className="document-error">{record.last_error}</span>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {declined && (
        <div className="review-notice" role="status">
          <strong>Reviewed {formatDate(review.timestamp)}:</strong>{' '}
          {VERDICT_LABELS[review.verdict] || review.verdict}. {review.summary}
          <p>
            The set was not badged and its last-amended date was not moved. The analysis
            below is the most recent material change.
          </p>
        </div>
      )}

      {analysis && (
        <div className="analysis-card">
          <div className="analysis-header">
            <h3>Analysis</h3>
            <div className="analysis-meta">
              <PriorityBadge priority={analysis.priority} solid />
              {verdict && VERDICT_LABELS[verdict] && (
                <span className="verdict-chip">{VERDICT_LABELS[verdict]}</span>
              )}
              <span className="analysis-date">{formatDate(analysis.date_time)}</span>
            </div>
          </div>

          {changedDocuments.length > 0 && (
            <p className="changed-documents-line">
              <strong>Changed:</strong> {changedDocuments.join(', ')}.{' '}
              {policySet.urls.length > changedDocuments.length && (
                <>
                  The other {policySet.urls.length - changedDocuments.length} document
                  {policySet.urls.length - changedDocuments.length === 1 ? '' : 's'} in this
                  set were checked and are unchanged.
                </>
              )}
            </p>
          )}

          <div className="analysis-summary">
            <strong>{analysis.summary}</strong>
          </div>

          {analysis.fingerprint?.length > 0 && (
            <div className="fingerprint-tags">
              {analysis.fingerprint.map((tag) => (
                <span className="fingerprint-tag" key={tag}>
                  {tag.replace('watchlist:', '')}
                </span>
              ))}
            </div>
          )}

          <h4>Detailed analysis</h4>
          <div className="analysis-content">
            <ReactMarkdown>{analysis.analysis || ''}</ReactMarkdown>
          </div>

          <div className="feedback-row">
            <span>Was this analysis useful?</span>
            <a
              className="feedback-button"
              href={feedbackUrl(policySet.setName, fileId, verdict, 'up')}
              target="_blank"
              rel="noopener noreferrer"
            >
              👍 Yes
            </a>
            <a
              className="feedback-button"
              href={feedbackUrl(policySet.setName, fileId, verdict, 'down')}
              target="_blank"
              rel="noopener noreferrer"
            >
              👎 No
            </a>
          </div>
        </div>
      )}

      <section className="diff-section">
        <h3>What changed</h3>
        <DiffView diff={diff} changedDocuments={changedDocuments} />
      </section>

      <section className="history-section">
        <h3>Change history</h3>
        <HistoryTimeline
          entries={historyState.entries}
          loading={historyState.loading}
          error={historyState.error}
        />
      </section>

      <details className="snapshot-disclosure">
        <summary>Full captured text ({Math.round((snapshot?.length || 0) / 1024)} kB)</summary>
        <div className="snapshot-container">
          <pre className="snapshot-content">{snapshot}</pre>
        </div>
      </details>
    </div>
  );
}

export default PolicyDetail;
