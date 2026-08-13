import React from 'react';
import { formatShortDay, getPriorityColor, isStale, STALE_AFTER_DAYS } from '../utils/constants';

/**
 * A priority badge that carries its date.
 *
 * The sidebar used to show the priority of the last change whenever it
 * happened, so a source could wear CRITICAL for months. An undated badge
 * trains people to ignore the badge, which is the opposite of what a priority
 * signal is for. Past STALE_AFTER_DAYS the badge fades and the date is shown
 * regardless of the `date` prop being requested.
 */
function PriorityBadge({ priority, date, solid = false, className = '' }) {
  if (!priority) return null;

  const stale = isStale(date);
  const label = priority.toUpperCase();
  const shown = date ? formatShortDay(date) : null;

  const style = solid
    ? { backgroundColor: getPriorityColor(priority) }
    : { color: getPriorityColor(priority) };

  return (
    <span
      className={`priority-badge${solid ? ' solid' : ''}${stale ? ' stale' : ''} ${className}`.trim()}
      style={style}
      title={
        stale && shown
          ? `Last change ${shown} — more than ${STALE_AFTER_DAYS} days ago`
          : undefined
      }
    >
      {label}
      {shown && <span className="priority-badge-date"> · {shown}</span>}
    </span>
  );
}

export default PriorityBadge;
