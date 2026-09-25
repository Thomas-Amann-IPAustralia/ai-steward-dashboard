import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { formatDay, primaryUrl, VERDICT_LABELS } from '../utils/constants';
import { eventsBetween, isMaterialEntry } from '../utils/series';
import { Legend, useChartTooltip } from './charts';
import Lettermark from './Lettermark';

const DAY_MS = 24 * 60 * 60 * 1000;
const PRIORITIES = ['critical', 'high', 'medium', 'low'];

const priorityOf = (entry) => {
  const value = (entry.priority || '').toLowerCase();
  return PRIORITIES.includes(value) ? value : 'unrated';
};

const monthTicks = (from, to) => {
  const ticks = [];
  const cursor = new Date(from);
  cursor.setDate(1);
  cursor.setHours(0, 0, 0, 0);
  cursor.setMonth(cursor.getMonth() + 1);
  while (cursor.getTime() <= to) {
    const month = cursor.toLocaleDateString('en-AU', { month: 'short' });
    ticks.push({
      at: ((cursor.getTime() - from) / (to - from)) * 100,
      label: cursor.getMonth() === 0 ? `${month} ${cursor.getFullYear()}` : month,
    });
    cursor.setMonth(cursor.getMonth() + 1);
  }
  return ticks;
};

/** A month label needs this much room clear of "Today" at the right edge. */
const TODAY_CLEARANCE_PX = 56;

/** The rendered width of an element, kept current as the layout changes. */
function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

const truncate = (text, length) => (text && text.length > length ? `${text.slice(0, length - 1).trimEnd()}…` : text);

export const TIMELINE_LEGEND = [
  { label: 'Critical', swatch: 'p-critical' },
  { label: 'High', swatch: 'p-high' },
  { label: 'Medium', swatch: 'p-medium' },
  { label: 'Low', swatch: 'p-low' },
  { label: 'Analysed, not material', swatch: 'p-none', shape: 'ring' },
];

/**
 * Every monitored source on one time axis, one lane each, a dot for every
 * change the model analysed. It answers a question no list can: which
 * providers rewrite their terms constantly, which never do, and whether a
 * change is part of a burst. Solid dots were judged material and carry
 * their priority's colour; hollow ones were analysed and let pass.
 */
function ChangeTimeline({ policySets, entries, days = 180, now = Date.now(), compact = false }) {
  const navigate = useNavigate();
  const { ref, show, hide, node } = useChartTooltip();
  const from = now - days * DAY_MS;

  const lanes = useMemo(
    () =>
      policySets
        .map((set) => {
          // Hollow dots first, so a solid (material) dot is never covered by one.
          const events = eventsBetween(entries?.[set.file_id], from, now).sort(
            (a, b) => isMaterialEntry(a) - isMaterialEntry(b) || a.time - b.time
          );
          return {
            set,
            events,
            material: events.filter(isMaterialEntry).length,
            latest: events.reduce((max, entry) => Math.max(max, entry.time), 0),
          };
        })
        .sort((a, b) => b.latest - a.latest || a.set.setName.localeCompare(b.set.setName)),
    [policySets, entries, from, now]
  );

  const ticks = useMemo(() => monthTicks(from, now), [from, now]);
  const [axisRef, axisWidth] = useWidth();

  const tipFor = (set, entry) => (
    <>
      <div className="chart-tip-title">{set.setName}</div>
      <div className="chart-tip-row">
        <span className={`tip-key ${isMaterialEntry(entry) ? `p-${priorityOf(entry)}` : 'p-none'}`} />
        <strong>{isMaterialEntry(entry) ? priorityOf(entry).replace(/^./, (c) => c.toUpperCase()) : 'Not material'}</strong>
        <span>{formatDay(entry.timestamp)}</span>
      </div>
      {entry.verdict && VERDICT_LABELS[entry.verdict] && !isMaterialEntry(entry) && (
        <div className="chart-tip-note">{VERDICT_LABELS[entry.verdict]}</div>
      )}
      {entry.summary && <div className="chart-tip-note">{truncate(entry.summary, 170)}</div>}
    </>
  );

  return (
    <div className={`change-timeline${compact ? ' compact' : ''}`} ref={ref}>
      <div className="tl-row tl-axis" aria-hidden="true">
        <span className="tl-label" />
        <div className="tl-track" ref={axisRef}>
          {ticks
            .filter((tick) => ((100 - tick.at) / 100) * axisWidth >= TODAY_CLEARANCE_PX)
            .map((tick) => (
              <span key={`${tick.label}-${tick.at}`} className="tl-tick" style={{ left: `${tick.at}%` }}>
                {tick.label}
              </span>
            ))}
          <span className="tl-tick today" style={{ left: '100%' }}>Today</span>
        </div>
        <span className="tl-count">Material</span>
      </div>

      {lanes.map(({ set, events, material, latest }) => (
        <div className="tl-row" key={set.file_id}>
          <Link className="tl-label" to={`/policy/${set.file_id}`} title={set.setName}>
            <Lettermark url={primaryUrl(set)} name={set.setName} size={20} />
            <span>{set.setName}</span>
          </Link>
          <div className="tl-track">
            <span className="visually-hidden">
              {events.length === 0
                ? `No analysed changes in the last ${days} days.`
                : `${material} material change${material === 1 ? '' : 's'} and ${events.length - material} analysed and let pass in the last ${days} days; the latest on ${formatDay(new Date(latest).toISOString())}.`}
            </span>
            {ticks.map((tick) => (
              <span key={tick.at} className="tl-grid" style={{ left: `${tick.at}%` }} aria-hidden="true" />
            ))}
            {events.map((entry) => (
              <button
                type="button"
                tabIndex={-1}
                aria-hidden="true"
                key={`${entry.timestamp}-${entry.analysis_path || ''}`}
                className={`tl-dot ${isMaterialEntry(entry) ? `p-${priorityOf(entry)}` : 'p-none'}`}
                style={{ left: `${((entry.time - from) / (now - from)) * 100}%` }}
                onMouseEnter={(event) => show(event, tipFor(set, entry))}
                onMouseLeave={hide}
                onClick={() => navigate(`/policy/${set.file_id}`)}
              />
            ))}
          </div>
          <span className={`tl-count${material ? '' : ' zero'}`}>{material}</span>
        </div>
      ))}

      {!compact && <Legend items={TIMELINE_LEGEND} />}
      {node}
    </div>
  );
}

export default ChangeTimeline;
