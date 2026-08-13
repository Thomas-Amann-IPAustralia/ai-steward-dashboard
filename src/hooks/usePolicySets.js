import { useState, useEffect } from 'react';
import { BASE_URL, fetchWithTimeout } from '../utils/constants';

/**
 * Loads hashes.json (the monitored sets and their state) alongside health.json
 * (whether each source is actually being read). A source that has not been
 * read successfully for months looks identical to a stable one unless the
 * health file is loaded with it.
 */
export function usePolicySets() {
  const [policySets, setPolicySets] = useState([]);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const controller = new AbortController();

    const load = async () => {
      setLoading(true);
      setError(null);
      const cacheBuster = `?v=${Date.now()}`;

      try {
        const response = await fetchWithTimeout(
          `${BASE_URL}/hashes.json${cacheBuster}`,
          { signal: controller.signal }
        );
        if (!response.ok) {
          throw new Error(`Failed to load monitored policies. Status: ${response.status}`);
        }
        const data = await response.json();

        const setList = Object.keys(data)
          .map((setName) => ({ setName, ...data[setName] }))
          .filter((item) => item.file_id && Array.isArray(item.urls) && item.urls.length > 0);

        if (setList.length === 0 && Object.keys(data).length > 0) {
          console.warn('Data in hashes.json appears to be in an old or invalid format.');
        }

        setPolicySets(setList);
      } catch (err) {
        if (err.name === 'AbortError') return;
        console.error('Failed to load or parse hashes.json:', err);
        setError('Could not load the list of monitored policies. The data file may be missing or corrupt.');
      } finally {
        setLoading(false);
      }

      // Health is supplementary: its absence must not blank the dashboard.
      try {
        const response = await fetchWithTimeout(
          `${BASE_URL}/health.json${cacheBuster}`,
          { signal: controller.signal }
        );
        if (response.ok) setHealth(await response.json());
      } catch (err) {
        if (err.name !== 'AbortError') console.warn('health.json unavailable:', err);
      }
    };

    load();
    return () => controller.abort();
  }, []);

  return { policySets, health, loading, error };
}
