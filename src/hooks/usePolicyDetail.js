import { useState, useEffect } from 'react';
import { BASE_URL, fetchWithTimeout } from '../utils/constants';

const EMPTY_ANALYSIS = {
  summary: 'No analysis found for this policy set.',
  analysis: 'This could be the first scan, or an error may have occurred during analysis.',
  date_time: 'Unknown',
  priority: 'low',
  verdict: null,
};

/**
 * Loads the three artefacts a detail page needs: the analysis, the unified
 * diff that produced it, and the full snapshot behind a disclosure. The diff
 * is the primary view; the snapshot is a fallback for sets last captured
 * before diffs existed.
 */
export function usePolicyDetail(fileId) {
  const [analysis, setAnalysis] = useState(null);
  const [diff, setDiff] = useState('');
  const [snapshot, setSnapshot] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!fileId) {
      setAnalysis(null);
      setDiff('');
      setSnapshot('');
      setError(null);
      return undefined;
    }

    const controller = new AbortController();

    const fetchDetail = async () => {
      setLoading(true);
      setError(null);
      setDiff('');
      const cacheBuster = `?v=${Date.now()}`;
      const opts = { signal: controller.signal };

      try {
        const [analysisRes, diffRes, snapshotRes] = await Promise.all([
          fetchWithTimeout(`${BASE_URL}/analysis/${fileId}.json${cacheBuster}`, opts),
          fetchWithTimeout(`${BASE_URL}/diffs/${fileId}.diff${cacheBuster}`, opts).catch(() => null),
          fetchWithTimeout(`${BASE_URL}/snapshots/${fileId}.txt${cacheBuster}`, opts),
        ]);

        setAnalysis(analysisRes.ok ? await analysisRes.json() : EMPTY_ANALYSIS);
        if (diffRes && diffRes.ok) setDiff(await diffRes.text());
        setSnapshot(
          snapshotRes.ok
            ? await snapshotRes.text()
            : 'Could not load the content snapshot for this policy set.'
        );
      } catch (err) {
        if (err.name !== 'AbortError') {
          console.error('Error loading policy set data:', err);
          setError(
            err.message === 'Failed to fetch'
              ? 'Could not reach the data files. Check your connection and try again.'
              : 'An error occurred while loading data. It may have timed out — try reloading.'
          );
        }
      } finally {
        setLoading(false);
      }
    };

    fetchDetail();
    return () => controller.abort();
  }, [fileId]);

  return { analysis, diff, snapshot, loading, error };
}
