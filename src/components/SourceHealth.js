import React from 'react';
import { formatRelative, HEALTH_LABELS } from '../utils/constants';

/**
 * Makes a broken source visible.
 *
 * When every fetch failed, the previous run's entry was copied forward and the
 * dashboard showed nothing unusual — so "stable since February" and "has not
 * been read since February" looked identical. The second is a silent false
 * negative on exactly the risk this tool exists to cover.
 */

export function HealthPill({ status }) {
  if (!status || status === 'ok') return null;
  return (
    <span className={`health-pill health-${status}`} title={HEALTH_LABELS[status]}>
      {status === 'failing' ? 'Not being read' : 'Read failed'}
    </span>
  );
}

export function SourceHealthNotice({ source }) {
  if (!source || source.status === 'ok') return null;

  const failing = source.failing || [];
  const severe = source.status === 'failing';

  return (
    <div className={`health-notice ${severe ? 'severe' : ''}`} role="status">
      <strong>
        {severe
          ? 'This source is not being read successfully.'
          : 'The last read of this source did not fully succeed.'}
      </strong>
      <p>
        {source.last_success
          ? `Last complete read ${formatRelative(source.last_success)}.`
          : 'It has never been read successfully.'}{' '}
        {severe
          ? 'Until this is fixed, "no changes" for this source means "not checked", not "nothing happened".'
          : 'The stored snapshot has been left untouched rather than overwritten with a bad capture.'}
      </p>
      {failing.length > 0 && (
        <ul className="health-notice-list">
          {failing.map((doc) => (
            <li key={doc.url}>
              <span className="health-doc-label">{doc.label || doc.url}</span>
              {doc.last_error && <span className="health-doc-error"> — {doc.last_error}</span>}
              {doc.consecutive_failures > 1 && (
                <span className="health-doc-count"> ({doc.consecutive_failures} runs)</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default SourceHealthNotice;
