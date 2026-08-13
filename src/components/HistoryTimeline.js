import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { BASE_URL, fetchWithTimeout, formatDay, VERDICT_LABELS } from '../utils/constants';
import PriorityBadge from './PriorityBadge';

const PAGE_SIZE = 12;

/**
 * The timeline over the archived analyses. Entries render from the index; the
 * full analysis is fetched only when a row is expanded, so a source with two
 * hundred archived analyses costs one small index file to display.
 */
function HistoryTimeline({ entries, loading, error }) {
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [expanded, setExpanded] = useState(null);
  const [detail, setDetail] = useState({});

  if (loading) return <div className="loading-message" aria-live="polite">Loading change history…</div>;
  if (error) return <div className="history-empty">{error}</div>;
  if (!entries || entries.length === 0) {
    return <div className="history-empty">No archived analyses for this policy set yet.</div>;
  }

  const toggle = async (entry) => {
    const key = entry.timestamp;
    if (expanded === key) {
      setExpanded(null);
      return;
    }
    setExpanded(key);

    if (detail[key] || !entry.analysis_path) return;
    try {
      const response = await fetchWithTimeout(`${BASE_URL}/${entry.analysis_path}`);
      if (response.ok) {
        const loaded = await response.json();
        setDetail((current) => ({ ...current, [key]: loaded }));
      } else {
        setDetail((current) => ({ ...current, [key]: { error: true } }));
      }
    } catch {
      setDetail((current) => ({ ...current, [key]: { error: true } }));
    }
  };

  return (
    <div className="history-timeline">
      <ol className="timeline-list">
        {entries.slice(0, visible).map((entry) => {
          const key = entry.timestamp;
          const open = expanded === key;
          const loaded = detail[key];

          return (
            <li className={`timeline-item${open ? ' open' : ''}`} key={key}>
              <button
                type="button"
                className="timeline-head"
                onClick={() => toggle(entry)}
                aria-expanded={open}
              >
                <span className="timeline-date">{formatDay(entry.timestamp)}</span>
                <span className="timeline-summary">
                  {entry.summary || 'Archived analysis'}
                </span>
                <span className="timeline-meta">
                  {entry.verdict && VERDICT_LABELS[entry.verdict] && (
                    <span className="verdict-chip">{VERDICT_LABELS[entry.verdict]}</span>
                  )}
                  <PriorityBadge priority={entry.priority} />
                </span>
              </button>

              {open && (
                <div className="timeline-body">
                  {entry.changed_documents?.length > 0 && (
                    <p className="timeline-documents">
                      Changed: {entry.changed_documents.join(', ')}
                    </p>
                  )}
                  {loaded?.error && <p>The archived analysis could not be loaded.</p>}
                  {loaded && !loaded.error && (
                    <ReactMarkdown>{loaded.analysis || ''}</ReactMarkdown>
                  )}
                  {!loaded && <p className="loading-message">Loading…</p>}
                </div>
              )}
            </li>
          );
        })}
      </ol>

      {visible < entries.length && (
        <button
          type="button"
          className="secondary-button"
          onClick={() => setVisible((n) => n + PAGE_SIZE)}
        >
          Show older ({entries.length - visible} remaining)
        </button>
      )}
    </div>
  );
}

export default HistoryTimeline;
