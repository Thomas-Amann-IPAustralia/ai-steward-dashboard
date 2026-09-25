import React, { useCallback, useRef, useState } from 'react';

/**
 * The dashboard's charts, drawn as plain HTML rather than with a charting
 * library: a handful of columns, strips and meters is less code than a
 * library's configuration, renders crisply at any width without measuring,
 * and follows the theme through the same CSS variables as everything else.
 *
 * Every mark carries a hover and focus tooltip, and every chart has a text
 * equivalent (an aria-label summary, and the tables and lists beside it), so
 * nothing is only readable by colour or by pointer.
 */

/** Rounds a maximum up to 1, 2 or 5 × 10ⁿ, so gridlines land on clean numbers. */
export function niceMax(value) {
  if (!value || value <= 1) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 5, 10].find((m) => m * power >= value);
  return step * power;
}

/** A tooltip anchored above whichever mark is hovered or focused. */
export function useChartTooltip() {
  const ref = useRef(null);
  const [tip, setTip] = useState(null);

  const show = useCallback((event, content) => {
    const box = ref.current?.getBoundingClientRect();
    const mark = event.currentTarget.getBoundingClientRect();
    if (!box) return;
    const half = Math.min(130, box.width / 2);
    const x = Math.min(Math.max(mark.left + mark.width / 2 - box.left, half), box.width - half);
    setTip({ x, y: mark.top - box.top, content });
  }, []);

  const hide = useCallback(() => setTip(null), []);

  const node = tip ? (
    <div className="chart-tip" style={{ left: tip.x, top: tip.y }} aria-hidden="true">
      {tip.content}
    </div>
  ) : null;

  return { ref, show, hide, node };
}

/** Tooltip body: the value leads, what it is follows. */
export function TipRows({ title, rows }) {
  return (
    <>
      {title && <div className="chart-tip-title">{title}</div>}
      {rows.map((row) => (
        <div className="chart-tip-row" key={row.label}>
          {row.swatch && <span className={`tip-key ${row.swatch}`} />}
          <strong>{row.value}</strong>
          <span>{row.label}</span>
        </div>
      ))}
    </>
  );
}

/**
 * Stacked columns over evenly spaced periods. `series` is listed bottom to
 * top; each has a `key`, a `label` and a CSS `swatch` class. With `compact`
 * it is a sparkline: no axis, no gridlines, still with tooltips.
 */
export function StackedColumns({
  rows,
  series,
  height = 120,
  titleOf = (row) => row.key,
  tickOf = () => null,
  onSelect,
  selectedKey,
  compact = false,
  ariaLabel,
  hint,
}) {
  const { ref, show, hide, node } = useChartTooltip();
  const max = niceMax(Math.max(0, ...rows.map((row) => row.total)));

  const tipFor = (row) => (
    <>
      <TipRows
        title={titleOf(row)}
        rows={
          series.length > 1
            ? [...series].reverse().map((s) => ({ label: s.label, value: row.counts[s.key] || 0, swatch: s.swatch }))
            : [{ label: series[0].label, value: row.total }]
        }
      />
      {hint && row.total > 0 && <div className="chart-tip-hint">{hint}</div>}
    </>
  );

  const Mark = onSelect ? 'button' : 'div';

  return (
    <div className={`cols-chart${compact ? ' compact' : ''}`} ref={ref} role={onSelect ? 'group' : 'img'} aria-label={ariaLabel}>
      <div className="cols-plot" style={{ height }}>
        {!compact && (
          <div className="cols-grid" aria-hidden="true">
            <span style={{ bottom: '100%' }}><em>{max}</em></span>
            <span style={{ bottom: '50%' }}><em>{max / 2 === Math.round(max / 2) ? max / 2 : ''}</em></span>
            <span className="baseline" style={{ bottom: 0 }} />
          </div>
        )}
        <div className={`cols-bars${selectedKey ? ' has-selection' : ''}`}>
          {rows.map((row) => (
            <Mark
              key={row.key}
              type={onSelect ? 'button' : undefined}
              className={`col${row.key === selectedKey ? ' selected' : ''}${row.total === 0 ? ' empty' : ''}`}
              onMouseEnter={(event) => show(event, tipFor(row))}
              onMouseLeave={hide}
              onFocus={onSelect ? (event) => show(event, tipFor(row)) : undefined}
              onBlur={onSelect ? hide : undefined}
              onClick={onSelect && row.total > 0 ? () => onSelect(row) : undefined}
              aria-pressed={onSelect ? row.key === selectedKey : undefined}
              aria-label={onSelect ? `${titleOf(row)}: ${row.total}` : undefined}
              disabled={onSelect ? row.total === 0 : undefined}
            >
              <span className="col-stack" style={{ height: `${(row.total / max) * 100}%` }}>
                {series.map((s) =>
                  row.counts[s.key] ? (
                    <span key={s.key} className={`seg ${s.swatch}`} style={{ flexGrow: row.counts[s.key] }} />
                  ) : null
                )}
              </span>
            </Mark>
          ))}
        </div>
      </div>
      {!compact && (
        <div className="cols-axis" aria-hidden="true">
          {rows.map((row, index) => (
            <span key={row.key}>{tickOf(row, index)}</span>
          ))}
        </div>
      )}
      {node}
    </div>
  );
}

/** A key for a chart's series: always present for two or more. */
export function Legend({ items }) {
  return (
    <ul className="chart-legend">
      {items.map((item) => (
        <li key={item.label} title={item.description}>
          <span className={`legend-key ${item.swatch}${item.shape ? ` ${item.shape}` : ''}`} aria-hidden="true" />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/** One horizontal bar split into labelled parts — e.g. sources by health. */
export function Meter({ parts, ariaLabel }) {
  const total = parts.reduce((sum, part) => sum + part.value, 0) || 1;
  return (
    <div className="meter" role="img" aria-label={ariaLabel}>
      {parts
        .filter((part) => part.value > 0)
        .map((part) => (
          <span
            key={part.label}
            className={`meter-part ${part.swatch}`}
            style={{ flexGrow: part.value / total }}
            title={`${part.value} ${part.label}`}
          />
        ))}
    </div>
  );
}

/**
 * A status-page strip: one cell per day. `cells` are `{ key, status, tip }`;
 * the colour is set by `status-<status>` classes, and the tooltip says what
 * happened in words.
 */
export function StatusStrip({ cells, ariaLabel }) {
  const { ref, show, hide, node } = useChartTooltip();
  return (
    <div className="status-strip" ref={ref} role="img" aria-label={ariaLabel}>
      {cells.map((cell) => (
        <span
          key={cell.key}
          className={`strip-cell status-${cell.status}`}
          onMouseEnter={(event) => show(event, cell.tip)}
          onMouseLeave={hide}
        />
      ))}
      {node}
    </div>
  );
}
