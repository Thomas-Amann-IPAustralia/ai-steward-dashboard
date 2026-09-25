import { useState, useEffect } from 'react';
import { BASE_URL, fetchWithTimeout } from '../utils/constants';

let cached = null;
let inflight = null;

const loadIndex = () => {
  if (!inflight) {
    inflight = fetchWithTimeout(`${BASE_URL}/history.json?v=${Date.now()}`)
      .then((response) => {
        if (!response.ok) throw new Error(`Status ${response.status}`);
        return response.json();
      })
      .then((data) => {
        cached = { entries: data?.entries || {}, generated_at: data?.generated_at || null };
        return cached;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
};

/**
 * Loads history.json, the index over the archived analyses in logs/.
 *
 * GitHub Pages serves no directory listing, so a year of archives has been
 * shipped in every build with no way for the app to enumerate it. The index is
 * generated at the end of each run; the timelines are a rendering job over it.
 * Fetched once and cached at module scope because it does not change while
 * the page is open, and shared by every view that draws from it.
 */
export function useHistoryIndex() {
  const [state, setState] = useState(() =>
    cached ? { entries: cached.entries, loading: false, error: null } : { entries: {}, loading: true, error: null }
  );

  useEffect(() => {
    if (cached) return undefined;
    let active = true;
    loadIndex()
      .then((index) => {
        if (active) setState({ entries: index.entries, loading: false, error: null });
      })
      .catch((err) => {
        console.warn('history.json unavailable:', err);
        if (active) setState({ entries: {}, loading: false, error: 'The change history index is not available yet.' });
      });
    return () => {
      active = false;
    };
  }, []);

  return state;
}

/** The archived analyses for one policy set, newest first. */
export function useHistory(fileId) {
  const { entries, loading, error } = useHistoryIndex();
  return { entries: fileId ? entries[fileId] ?? [] : [], loading, error };
}
