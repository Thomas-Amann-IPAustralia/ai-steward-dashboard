import React from 'react';
import { formatDate, formatRelative, REPO_URL, runStaleness } from '../utils/constants';

/**
 * Says when the monitor itself has stopped running.
 *
 * Everything else on this page reports on the *sources*. Nothing reported on
 * the thing doing the reporting — so if the workflow stopped, every badge and
 * every "last checked" would freeze at its last value and the dashboard would
 * look entirely normal. A frozen dashboard that looks current is worse than no
 * dashboard, because it is trusted.
 *
 * Driven by health.json's own `generated_at`, which only a completed run
 * writes. A missing health.json is treated as stale rather than fine: the
 * absence of evidence is exactly the case being guarded against.
 */
function StaleRunNotice({ health }) {
  const { stale, hours, generatedAt } = runStaleness(health);
  if (!stale) return null;

  return (
    <div className="stale-run-notice" role="alert">
      <strong>
        {generatedAt
          ? `The monitor has not completed a run since ${formatDate(generatedAt)}.`
          : 'No completed monitoring run can be confirmed.'}
      </strong>{' '}
      {generatedAt
        ? `That is ${formatRelative(generatedAt)} — everything below may be out of date, and "no changes" means "not checked".`
        : 'The health report is missing or unreadable, so nothing below can be treated as current.'}{' '}
      <a href={`${REPO_URL}/actions`} target="_blank" rel="noopener noreferrer">
        Check the workflow
      </a>
      {hours !== null && hours >= 24 * 7 && ' — this has been the case for over a week.'}
    </div>
  );
}

export default StaleRunNotice;
