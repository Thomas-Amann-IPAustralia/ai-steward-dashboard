import { useEffect, useState } from 'react';
import { BASE_URL, fetchWithTimeout } from '../utils/constants';

let cached = null;
let inflight = null;

const EMPTY = { items: [], sources: {}, generated_at: null, window_days: null };

/**
 * Loads news/feed.json — news and AI-incident items, and the health of the
 * feeds behind them.
 *
 * Supplementary in the same way health.json is: a missing or failed feed
 * degrades the news and incident views to a notice, and never blanks the
 * policy dashboard. Fetched once per page load and shared by every view.
 */
export function useNews() {
  const [state, setState] = useState(() =>
    cached ? { feed: cached, loading: false, error: null } : { feed: EMPTY, loading: true, error: null }
  );

  useEffect(() => {
    if (cached) return undefined;
    let active = true;

    if (!inflight) {
      inflight = fetchWithTimeout(`${BASE_URL}/news/feed.json?v=${Date.now()}`)
        .then((response) => {
          if (!response.ok) throw new Error(`Status ${response.status}`);
          return response.json();
        })
        .then((data) => {
          cached = { ...EMPTY, ...data, items: Array.isArray(data?.items) ? data.items : [] };
          return cached;
        })
        .finally(() => {
          inflight = null;
        });
    }

    inflight
      .then((feed) => {
        if (active) setState({ feed, loading: false, error: null });
      })
      .catch((err) => {
        console.warn('news/feed.json unavailable:', err);
        if (active) {
          setState({
            feed: EMPTY,
            loading: false,
            error: 'The news and incident feed is not available yet.',
          });
        }
      });

    return () => {
      active = false;
    };
  }, []);

  return state;
}
