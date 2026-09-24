import React, { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { formatRelative } from '../utils/constants';
import {
  dayLabel,
  filterItems,
  groupByDay,
  isNew,
  NEWS_CATEGORIES,
  pickTopStories,
  RELEVANCE,
} from '../utils/news';
import { NewsRow, TopStory } from './FeedCards';

const PAGE_SIZE = 40;

/**
 * The news feed: Australian government announcements, the reporting around
 * them, analysis, regulators overseas and the AI providers APS staff use.
 *
 * Built to be read at a glance: the few stories that matter most lead, and
 * everything else is one scannable row — relevance as a coloured edge, the
 * outlet as a mark, one line of summary. It opens on "Most relevant" (items
 * scored 2 or 3), because a feed that shows everything is a feed nobody
 * reads; the filters live in the URL so a view can be shared with a team.
 */
function NewsFeed({ feed, loading, error, since, policyNames }) {
  const [params, setParams] = useSearchParams();
  const [visible, setVisible] = useState(PAGE_SIZE);

  const query = params.get('q') || '';
  const category = params.get('category') || '';
  const everything = params.get('show') === 'all';
  const relatedOnly = params.get('related') === '1';
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
    filterItems(news, { minRelevance, query, relatedOnly }).forEach((item) => {
      counts[''] += 1;
      counts[item.category] = (counts[item.category] || 0) + 1;
    });
    return counts;
  }, [news, minRelevance, query, relatedOnly]);

  const results = useMemo(
    () => filterItems(news, { category, minRelevance, query, relatedOnly }),
    [news, category, minRelevance, query, relatedOnly]
  );

  // Lead stories only on the default browsing view: when searching, the
  // reader wants every match in order, not an editorial selection.
  const topStories = useMemo(() => (query ? [] : pickTopStories(results)), [results, query]);
  const rest = useMemo(() => {
    const lead = new Set(topStories.map((item) => item.id));
    return results.filter((item) => !lead.has(item.id));
  }, [results, topStories]);
  const groups = useMemo(() => groupByDay(rest.slice(0, visible)), [rest, visible]);

  const newCount = useMemo(() => results.filter((item) => isNew(item, since)).length, [results, since]);
  const sourceCount = Object.values(feed.sources || {}).filter((s) => s.kind === 'news').length;

  return (
    <div className="feed-page news-page">
      <div className="page-header">
        <div>
          <h2>News</h2>
          <p className="page-subtitle">
            {loading
              ? 'Loading…'
              : `${news.length} stories from ${sourceCount} sources, last ${feed.window_days || 45} days` +
                (feed.generated_at ? ` · updated ${formatRelative(feed.generated_at)}` : '')}
          </p>
        </div>
        <ul className="relevance-key" aria-label="Relevance key">
          {[3, 2, 1].map((level) => (
            <li key={level} className={`rel-${level}`} title={RELEVANCE[level].description}>
              {RELEVANCE[level].label}
            </li>
          ))}
        </ul>
      </div>

      {error && <div className="notice-card">{error}</div>}

      <div className="filter-bar" role="search">
        <div className="filter-row">
          <input
            type="search"
            className="search-bar"
            placeholder="Search headlines and summaries…"
            value={query}
            onChange={(event) => update('q', event.target.value)}
            aria-label="Search news"
          />
          <div className="segmented" role="group" aria-label="Relevance">
            <button type="button" aria-pressed={!everything} onClick={() => update('show', '')}>
              Most relevant
            </button>
            <button type="button" aria-pressed={everything} onClick={() => update('show', 'all')}>
              Everything
            </button>
          </div>
        </div>
        <div className="filter-chips" role="group" aria-label="Filter the feed">
          {['', ...NEWS_CATEGORIES].map((value) => (
            <button
              key={value || 'all'}
              type="button"
              className={`filter-chip ${category === value ? 'active' : ''}`}
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
          <button
            type="button"
            className={`filter-chip toggle-chip ${relatedOnly ? 'active' : ''}`}
            aria-pressed={relatedOnly}
            onClick={() => update('related', relatedOnly ? '' : '1')}
            title="Only stories that name a provider or agency whose policies are monitored here"
          >
            Monitored providers only
          </button>
        </div>
      </div>

      {newCount > 0 && (
        <p className="result-count" aria-live="polite">
          {newCount} new since your last visit
        </p>
      )}

      {!loading && results.length === 0 && !error && (
        <div className="notice-card">
          Nothing matches.{' '}
          {!everything ? 'Try “Everything”, or clear the search.' : 'Try clearing the search or the filters.'}
        </div>
      )}

      {topStories.length > 0 && (
        <section className="top-stories" aria-labelledby="top-stories-title">
          <h3 id="top-stories-title" className="day-heading">Top stories</h3>
          <div className="top-stories-grid">
            {topStories.map((item) => (
              <TopStory key={item.id} item={item} since={since} policyNames={policyNames} />
            ))}
          </div>
        </section>
      )}

      {groups.map((group) => (
        <section className="day-group" key={group.key} aria-label={dayLabel(group.date)}>
          <h3 className="day-heading">
            {dayLabel(group.date)}
            <span className="day-count">{group.items.length}</span>
          </h3>
          <div className="news-list">
            {group.items.map((item) => (
              <NewsRow key={item.id} item={item} since={since} policyNames={policyNames} />
            ))}
          </div>
        </section>
      ))}

      {visible < rest.length && (
        <button type="button" className="secondary-button" onClick={() => setVisible((n) => n + PAGE_SIZE)}>
          Show more ({rest.length - visible} remaining)
        </button>
      )}

      <aside className="legend">
        <h3>How stories are chosen and ranked</h3>
        <dl>
          {[3, 2, 1].map((level) => (
            <React.Fragment key={level}>
              <dt>{RELEVANCE[level].label}</dt>
              <dd>{RELEVANCE[level].description}</dd>
            </React.Fragment>
          ))}
        </dl>
        <p>
          General news feeds only contribute stories with AI in the headline; live blogs and
          podcasts are left out. Repeat coverage of one event is folded into a single story —
          “+4 outlets” lists the rest. Each story is scored against the rubric above, first by
          keywords and then by the model, which also writes the one-line summary using only what
          the story itself says. Headlines always link to the original.
        </p>
      </aside>
    </div>
  );
}

export default NewsFeed;
