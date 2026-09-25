import React, { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { formatRelative, formatShortDay } from '../utils/constants';
import {
  blurbOf,
  dayKey,
  dayLabel,
  filterItems,
  groupByDay,
  isNew,
  NEWS_CATEGORIES,
  pickTopStories,
  RELEVANCE,
} from '../utils/news';
import { dailySeries, dayTime } from '../utils/series';
import { Legend, StackedColumns } from './charts';
import { NewsRow, TopStory } from './FeedCards';
import Icon from './Icon';

const PAGE_SIZE = 40;
const PULSE_DAYS = 30;

const TIERS = [
  { key: 1, label: RELEVANCE[1].label, swatch: 'rel-1', description: RELEVANCE[1].description },
  { key: 2, label: RELEVANCE[2].label, swatch: 'rel-2', description: RELEVANCE[2].description },
  { key: 3, label: RELEVANCE[3].label, swatch: 'rel-3', description: RELEVANCE[3].description },
];

const dayTitle = (key) => new Date(dayTime(key)).toISOString();

/**
 * The news feed: Australian government announcements, the reporting around
 * them, analysis, regulators overseas and the AI providers APS staff use.
 *
 * Built to be read at a glance: a pulse chart of the last month shows when
 * the news broke (click a day to read just that day), the few stories that
 * matter most lead, and everything else is one scannable row. It opens on
 * "Most relevant" (items scored 2 or 3), because a feed that shows everything
 * is a feed nobody reads; the filters live in the URL so a view can be shared
 * with a team. News is for reading — nothing here is marked as a call to act.
 */
function NewsFeed({ feed, loading, error, since, policyNames }) {
  const [params, setParams] = useSearchParams();
  const [visible, setVisible] = useState(PAGE_SIZE);

  const query = params.get('q') || '';
  const category = params.get('category') || '';
  const everything = params.get('show') === 'all';
  const relatedOnly = params.get('related') === '1';
  const day = params.get('day') || '';
  const minRelevance = everything ? 1 : 2;

  const update = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setVisible(PAGE_SIZE);
  };

  const news = useMemo(() => (feed.items || []).filter((item) => item.kind === 'news'), [feed.items]);

  const categoryCounts = useMemo(() => {
    const counts = { '': 0 };
    filterItems(news, { minRelevance, query, relatedOnly })
      .filter((item) => !day || dayKey(item.published) === day)
      .forEach((item) => {
        counts[''] += 1;
        counts[item.category] = (counts[item.category] || 0) + 1;
      });
    return counts;
  }, [news, minRelevance, query, relatedOnly, day]);

  // Everything but the day: what the pulse chart draws.
  const beforeDay = useMemo(
    () => filterItems(news, { category, minRelevance, query, relatedOnly }),
    [news, category, minRelevance, query, relatedOnly]
  );
  const results = useMemo(
    () => (day ? beforeDay.filter((item) => dayKey(item.published) === day) : beforeDay),
    [beforeDay, day]
  );
  const pulse = useMemo(
    () => dailySeries(beforeDay, { days: PULSE_DAYS, seriesOf: (item) => item.relevance || 1 }),
    [beforeDay]
  );
  const tiers = TIERS.filter((tier) => tier.key >= minRelevance);

  // Lead stories only on the default browsing view: when searching, or
  // reading one day, the reader wants every match in order, not a selection.
  const topStories = useMemo(() => (query || day ? [] : pickTopStories(results)), [results, query, day]);
  const rest = useMemo(() => {
    const lead = new Set(topStories.map((item) => item.id));
    return results.filter((item) => !lead.has(item.id));
  }, [results, topStories]);
  const groups = useMemo(() => groupByDay(rest.slice(0, visible)), [rest, visible]);

  const newCount = useMemo(() => results.filter((item) => isNew(item, since)).length, [results, since]);
  const sourceCount = Object.values(feed.sources || {}).filter((s) => s.kind === 'news').length;

  return (
    <div className="page feed-page news-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">News</p>
          <h1>AI news for the APS</h1>
          <p className="page-sub">
            {loading
              ? 'Loading…'
              : `${news.length} stories from ${sourceCount} sources over the last ${feed.window_days || 45} days` +
                (feed.generated_at ? ` · updated ${formatRelative(feed.generated_at)}` : '')}
          </p>
        </div>
      </header>

      {error && (
        <div className="callout callout-info">
          <Icon name="alert" size={18} className="callout-icon" />
          <div className="callout-body">{error}</div>
        </div>
      )}

      <div className="toolbar" role="search">
        <label className="input-with-icon grow">
          <Icon name="search" size={16} />
          <input
            type="search"
            placeholder="Search headlines and summaries…"
            value={query}
            onChange={(event) => update('q', event.target.value)}
            aria-label="Search news"
          />
        </label>
        <div className="segmented" role="group" aria-label="Relevance">
          <button type="button" aria-pressed={!everything} onClick={() => update('show', '')}>
            Most relevant
          </button>
          <button type="button" aria-pressed={everything} onClick={() => update('show', 'all')}>
            Everything
          </button>
        </div>
        <button
          type="button"
          className={`filter-chip toggle-chip${relatedOnly ? ' active' : ''}`}
          aria-pressed={relatedOnly}
          onClick={() => update('related', relatedOnly ? '' : '1')}
          title="Only stories that name a provider or agency whose policies are monitored here"
        >
          <Icon name="link" size={14} />
          Monitored providers
        </button>
      </div>
      <div className="chip-row scroll" role="group" aria-label="Filter the feed">
        {['', ...NEWS_CATEGORIES].map((value) => (
          <button
            key={value || 'all'}
            type="button"
            className={`filter-chip${category === value ? ' active' : ''}`}
            aria-pressed={category === value}
            // An empty category is shown, so the reader knows it was
            // looked at, but not offered as a dead end.
            disabled={!categoryCounts[value] && category !== value}
            onClick={() => update('category', value)}
          >
            {value || 'All'}
            <span className="chip-count">{categoryCounts[value] || 0}</span>
          </button>
        ))}
      </div>

      {!loading && news.length > 0 && (
        <section className="card pulse-card" aria-labelledby="pulse-title">
          <div className="card-head">
            <div>
              <h2 id="pulse-title">News pulse</h2>
              <p className="card-sub">Stories per day over the last {PULSE_DAYS} days, by relevance. Select a day to read it.</p>
            </div>
            <Legend items={[...tiers].reverse()} />
          </div>
          <StackedColumns
            rows={pulse}
            series={tiers}
            height={110}
            titleOf={(row) => dayLabel(dayTitle(row.key))}
            tickOf={(row, index) =>
              index % 7 === (pulse.length - 1) % 7 ? formatShortDay(dayTitle(row.key)) : null
            }
            onSelect={(row) => update('day', row.key === day ? '' : row.key)}
            selectedKey={day}
            hint={day ? 'Click to show every day' : 'Click to read this day'}
            ariaLabel={`Stories per day over the last ${PULSE_DAYS} days`}
          />
        </section>
      )}

      {(day || newCount > 0) && (
        <div className="result-bar" aria-live="polite">
          {day && (
            <button type="button" className="active-filter" onClick={() => update('day', '')}>
              <Icon name="calendar" size={14} />
              {dayLabel(dayTitle(day))} · {results.length} stor{results.length === 1 ? 'y' : 'ies'}
              <Icon name="x" size={14} />
              <span className="visually-hidden">Show every day</span>
            </button>
          )}
          {newCount > 0 && <span className="result-count">{newCount} new since your last visit</span>}
        </div>
      )}

      {!loading && results.length === 0 && !error && (
        <div className="empty-state card">
          <span className="empty-icon"><Icon name="search" size={20} /></span>
          <div>
            <strong>Nothing matches</strong>
            <p>{!everything ? 'Try “Everything”, or clear the search.' : 'Try clearing the search or the filters.'}</p>
          </div>
        </div>
      )}

      {topStories.length > 0 && (
        <section className="top-stories" aria-labelledby="top-stories-title">
          <h2 id="top-stories-title" className="section-label">Top stories</h2>
          <div className={`top-stories-grid count-${topStories.length}${blurbOf(topStories[0]) ? ' lead-rich' : ''}`}>
            {topStories.map((item, index) => (
              <TopStory key={item.id} item={item} since={since} policyNames={policyNames} featured={index === 0} />
            ))}
          </div>
        </section>
      )}

      {groups.map((group) => (
        <section className="day-group" key={group.key} aria-label={dayLabel(group.date)}>
          <h2 className="day-heading">
            {dayLabel(group.date)}
            <span className="day-count">{group.items.length}</span>
          </h2>
          <div className="news-list card flush">
            {group.items.map((item) => (
              <NewsRow key={item.id} item={item} since={since} policyNames={policyNames} />
            ))}
          </div>
        </section>
      ))}

      {visible < rest.length && (
        <button type="button" className="btn btn-secondary btn-block" onClick={() => setVisible((n) => n + PAGE_SIZE)}>
          Show more ({rest.length - visible} remaining)
        </button>
      )}

      <aside className="card legend-card">
        <h2>How stories are chosen and ranked</h2>
        <dl className="legend-grid">
          {[3, 2, 1].map((level) => (
            <div key={level}>
              <dt>
                <span className={`signal signal-${level}`} aria-hidden="true">
                  <span className="signal-bars"><i /><i /><i /></span>
                </span>
                {RELEVANCE[level].label}
              </dt>
              <dd>{RELEVANCE[level].description}</dd>
            </div>
          ))}
        </dl>
        <p className="muted">
          General news feeds only contribute stories with AI in the headline; live blogs and podcasts are left out.
          Repeat coverage of one event is folded into a single story — “+4 outlets” lists the rest. Each story is scored
          against the rubric above, first by keywords and then by the model, which also writes the one-line summary
          using only what the story itself says. Headlines always link to the original. Relevance says how closely a
          story touches APS work; the only changes this dashboard asks you to review are to the monitored policies.
        </p>
      </aside>
    </div>
  );
}

export default NewsFeed;
