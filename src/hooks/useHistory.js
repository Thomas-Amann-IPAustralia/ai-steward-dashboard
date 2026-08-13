import { useState, useEffect } from 'react';
import { BASE_URL, fetchWithTimeout } from '../utils/constants';

let cached = null;

/**
 * Loads history.json, the index over the archived analyses in logs/.
 *
 * GitHub Pages serves no directory listing, so a year of archives has been
 * shipped in every build with no way for the app to enumerate it. The index is
 * generated at the end of each run; the timeline is a rendering job over it.
 * Cached at module scope because it does not change while the page is open.
 */
export function useHistory(fileId) {
  const [entries, setEntries] = useState(() => (cached ? cached.entries?.[fileId] ?? [] : []));
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!fileId) {
      setEntries([]);
      return undefined;
    }

    if (cached) {
      setEntries(cached.entries?.[fileId] ?? []);
      setLoading(false);
      return undefined;
    }

    const controller = new AbortController();

    const load = async () => {
      setLoading(true);
      try {
        const response = await fetchWithTimeout(
          `${BASE_URL}/history.json?v=${Date.now()}`,
          { signal: controller.signal }
        );
        if (!response.ok) throw new Error(`Status ${response.status}`);
        cached = await response.json();
        setEntries(cached.entries?.[fileId] ?? []);
        setError(null);
      } catch (err) {
        if (err.name === 'AbortError') return;
        console.warn('history.json unavailable:', err);
        setError('The change history index is not available yet.');
      } finally {
        setLoading(false);
      }
    };

    load();
    return () => controller.abort();
  }, [fileId]);

  return { entries, loading, error };
}
