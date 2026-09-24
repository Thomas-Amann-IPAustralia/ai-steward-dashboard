import React, { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { formatRelative } from '../utils/constants';
import { dayLabel, filterItems, groupByDay, isNew, NEWS_CATEGORIES, RELEVANCE } from '../utils/news';
import { NewsCard } from './FeedCards';

const PAGE_SIZE = 40;

/**
 * The news feed: Australian government announcements, the reporting around
 * them, regulators overseas and the AI providers APS staff use.
 *
 * It opens on "Most relevant" — the items scored 2 or 3 — because a feed that
 * shows everything is a feed nobody reads. Everything is one click away, and
 * the filters live in the URL so a filtered view can be shared with a team.
 */
function NewsFeed({ feed, loading, error, since, policyNames }) {
  const [params, setParams] = useSearchParams();
  const [visible, setVisible] = useState(PAGE_SIZE);

  const query = params.get('q') || '';
  const category = params.get('category') || '';
  const everything = params.get('show') === 'all';
  const relatedOnly = params.get('related') === '1';

  const update = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setVisible(PAGE_SIZE);
  };

  const news = useMemo(() => (feed.items || []).filter((item) => item.kind === 'news'), [feed.items]);
  const results = useMemo(
    () =>
      filterItems(news, {
        category,
        minRelevance: everything ? 1 : 2,
        query,
        relatedOnly,
      }),
    [news, category, everything, query, relatedOnly]
  );
  const groups = useMemo(() => groupByDay(results.slice(0, visible)), [results, visible]);
  const newCount = useMemo(() => results.filter((item) => isNew(item, since)).length, [results, since]);
  const sourceCount = Object.values(feed.sources || {}).filter((s) => s.kind === 'news').length;

  return (
    <div className="feed-page">
      <div className="page-header">
        <div>
          <h2>News</h2>
          <p className="page-subtitle">
            {loading
              ? 'Loading…'
              : `${news.length} items from ${sourceCount} sources over the last ${feed.window_days || 45} days` +
                (feed.generated_at ? ` · updated ${formatRelative(feed.generated_at)}` : '')}
          </p>
        </div>
      </div>

      {error && <div className="notice-card">{error}</div>}

      <div className="filter-bar" role="search">
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
        <div className="filter-chips" role="group" aria-label="Source category">
          {['', ...NEWS_CATEGORIES].map((value) => (
            <button
              key={value || 'all'}
              type="button"
              className={`filter-chip ${category === value ? 'active' : ''}`}
              aria-pressed={category === value}
              onClick={() => update('category', value)}
            >
              {value || 'All sources'}
            </button>
          ))}
        </div>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={relatedOnly}
            onChange={(event) => update('related', event.target.checked ? '1' : '')}
          />
          Only items about a monitored policy or provider
        </label>
      </div>

      <p className="result-count" aria-live="polite">
        {results.length} item{results.length === 1 ? '' : 's'}
        {newCount > 0 && ` · ${newCount} new since your last visit`}
        {!everything && results.length > 0 && (
          <>
            {' · '}
            <span className="muted">
              showing “{RELEVANCE[3].label}” and “{RELEVANCE[2].label}” — choose Everything to include
              “{RELEVANCE[1].label}”
            </span>
          </>
        )}
      </p>

      {!loading && results.length === 0 && !error && (
        <div className="notice-card">
          Nothing matches.{' '}
          {!everything ? 'Try “Everything”, or clear the search.' : 'Try clearing the search or the source filter.'}
        </div>
      )}

      {groups.map((group) => (
        <section className="day-group" key={group.key} aria-label={dayLabel(group.date)}>
          <h3 className="day-heading">{dayLabel(group.date)}</h3>
          <div className="feed-list">
            {group.items.map((item) => (
              <NewsCard key={item.id} item={item} since={since} policyNames={policyNames} />
            ))}
          </div>
        </section>
      ))}

      {visible < results.length && (
        <button type="button" className="secondary-button" onClick={() => setVisible((n) => n + PAGE_SIZE)}>
          Show more ({results.length - visible} remaining)
        </button>
      )}

      <aside className="legend">
        <h3>How items are ranked</h3>
        <dl>
          {[3, 2, 1].map((level) => (
            <React.Fragment key={level}>
              <dt>{RELEVANCE[level].label}</dt>
              <dd>{RELEVANCE[level].description}</dd>
            </React.Fragment>
          ))}
        </dl>
        <p>
          General feeds only contribute items that mention AI. Each item is scored against the
          same rubric, first by keywords and then by the model, which also writes the short
          summary — using only what the item itself says. Headlines always link to the original.
        </p>
      </aside>
    </div>
  );
}

export default NewsFeed;
