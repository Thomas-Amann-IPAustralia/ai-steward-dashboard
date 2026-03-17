import React from 'react';
import { useParams } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { usePolicyDetail } from '../hooks/usePolicyDetail';
import { formatDate, getPriorityColor } from '../utils/constants';

function PolicyDetail({ policySets }) {
  const { fileId } = useParams();
  const { analysis, snapshot, loading, error } = usePolicyDetail(fileId);

  const policySet = policySets.find(p => p.file_id === fileId);

  if (loading) {
    return <div className="loading-message">Loading page data...</div>;
  }

  if (error) {
    return <div className="error-message">{error}</div>;
  }

  if (!policySet) {
    return (
      <div className="placeholder">
        <h2>Policy Not Found</h2>
        <p>The selected policy could not be found. Please select a policy from the sidebar.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="content-header">
        <h2>Analysis for: {policySet.setName}</h2>
        <div className="source-urls">
          <strong>Source URL(s):</strong>
          <ul>
            {policySet.urls.map(urlObj => (
              <li key={urlObj.url}>
                <a href={urlObj.url} target="_blank" rel="noopener noreferrer">
                  {urlObj.url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {analysis && (
        <div className="analysis-card">
          <div className="analysis-header">
            <h3>Analysis Summary</h3>
            <div className="analysis-meta">
              <span
                className="priority-badge"
                style={{ backgroundColor: getPriorityColor(analysis.priority) }}
              >
                {analysis.priority?.toUpperCase() || 'UNKNOWN'}
              </span>
              <span className="analysis-date">{formatDate(analysis.date_time)}</span>
            </div>
          </div>
          <div className="analysis-summary"><strong>{analysis.summary}</strong></div>
          <h4>Detailed Analysis</h4>
          <div className="analysis-content"><ReactMarkdown>{analysis.analysis}</ReactMarkdown></div>
        </div>
      )}

      <hr />

      <h3>Aggregated Content Snapshot</h3>
      <div className="snapshot-container">
        <pre className="snapshot-content">{snapshot}</pre>
      </div>
    </div>
  );
}

export default PolicyDetail;
