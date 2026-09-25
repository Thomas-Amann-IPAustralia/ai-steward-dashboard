import React from 'react';
import { formatShortDay } from '../utils/constants';
import { DAY_STATUS_LABELS, dayTime, statusStrip } from '../utils/series';
import { StatusStrip } from './charts';

/** One day of a source's checks, in words, for the strip's tooltip. */
function dayTip(cell) {
  const { day } = cell;
  const date = formatShortDay(new Date(dayTime(cell.key)).toISOString());
  const rows = [];
  if (day) {
    rows.push(`${day.checks} check${day.checks === 1 ? '' : 's'}`);
    if (day.rejected) rows.push(`${day.rejected} rejected`);
    if (day.failed) rows.push(`${day.failed} failed`);
    if (day.filtered) rows.push(`${day.filtered} set aside`);
    if (day.analysed) rows.push(`${day.analysed} analysed`);
  }
  return (
    <>
      <div className="chart-tip-title">{date}</div>
      <div className="chart-tip-row">
        <span className={`tip-key status-${cell.status}`} />
        <strong>{DAY_STATUS_LABELS[cell.status]}</strong>
      </div>
      {rows.length > 0 && <div className="chart-tip-note">{rows.join(' · ')}</div>}
    </>
  );
}

/**
 * A month of one source's checks as a status-page strip: a cell per day,
 * coloured by what that day amounted to and explained on hover.
 */
function SourceStrip({ daily, days = 30, label }) {
  const cells = statusStrip(daily, { days }).map((cell) => ({ ...cell, tip: dayTip(cell) }));
  const counts = cells.reduce((acc, cell) => ({ ...acc, [cell.status]: (acc[cell.status] || 0) + 1 }), {});
  const summary = Object.entries(counts)
    .map(([status, n]) => `${n} ${DAY_STATUS_LABELS[status].toLowerCase()}`)
    .join(', ');
  return <StatusStrip cells={cells} ariaLabel={`${label ? `${label}, ` : ''}last ${days} days: ${summary}`} />;
}

export default SourceStrip;
