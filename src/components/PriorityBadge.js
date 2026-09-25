import React from 'react';
import { formatShortDay, isStale, STALE_AFTER_DAYS } from '../utils/constants';

const KNOWN = new Set(['critical', 'high', 'medium', 'low']);

const ADOPTION_TITLE = 'An update to a register of what other agencies have published — not rated for risk';

/**
 * A priority badge that carries its date.
 *
 * The sidebar used to show the priority of the last change whenever it
 * happened, so a source could wear CRITICAL for months. An undated badge
 * trains people to ignore the badge, which is the opposite of what a priority
 * signal is for. Past STALE_AFTER_DAYS the badge fades and the date is shown
 * regardless of the `date` prop being requested.
 *
 * An adoption register's changes carry no risk rating, so for `kind`
 * "adoption" the badge says what the change is instead of how urgent it is.
 */
function PriorityBadge({ priority, date, kind, solid = false, className = '' }) {
  if (!priority) return null;

  const adoption = kind === 'adoption';
  const key = adoption ? 'adoption' : priority.toLowerCase();
  const stale = date !== undefined && isStale(date);
  const label = adoption ? 'Adoption update' : key.charAt(0).toUpperCase() + key.slice(1);
  const shown = date ? formatShortDay(date) : null;

  return (
    <span
      className={`priority-badge p-${adoption || KNOWN.has(key) ? key : 'none'}${solid ? ' solid' : ''}${stale ? ' stale' : ''} ${className}`.trim()}
      title={
        stale && shown
          ? `Last change ${shown} — more than ${STALE_AFTER_DAYS} days ago`
          : adoption
            ? ADOPTION_TITLE
            : `${label} priority`
      }
    >
      <span className="priority-dot" aria-hidden="true" />
      {label}
      {shown && <span className="priority-badge-date"> · {shown}</span>}
    </span>
  );
}

export default PriorityBadge;
