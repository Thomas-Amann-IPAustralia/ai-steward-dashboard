import { useState, useEffect, useRef } from 'react';
import { BASE_URL } from '../utils/constants';

export function usePolicyDetail(fileId) {
  const [analysis, setAnalysis] = useState(null);
  const [snapshot, setSnapshot] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);

  useEffect(() => {
    if (!fileId) {
      setAnalysis(null);
      setSnapshot('');
      setError(null);
      return;
    }

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const fetchDetail = async () => {
      setLoading(true);
      setError(null);
      try {
        const cacheBuster = `?v=${Date.now()}`;
        const [analysisRes, snapshotRes] = await Promise.all([
          fetch(`${BASE_URL}/analysis/${fileId}.json${cacheBuster}`, { signal: controller.signal }),
          fetch(`${BASE_URL}/snapshots/${fileId}.txt${cacheBuster}`, { signal: controller.signal }),
        ]);

        if (analysisRes.ok) {
          setAnalysis(await analysisRes.json());
        } else {
          setAnalysis({
            summary: 'No analysis found for this policy set.',
            analysis: 'This could be the first scan or an error might have occurred during analysis.',
            date_time: 'Unknown',
            priority: 'low',
          });
        }

        if (snapshotRes.ok) {
          setSnapshot(await snapshotRes.text());
        } else {
          setSnapshot('Could not load the content snapshot for this policy set.');
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          console.error('Error loading policy set data:', err);
          setError('An error occurred while loading data.');
        }
      } finally {
        setLoading(false);
      }
    };

    fetchDetail();
    return () => controller.abort();
  }, [fileId]);

  return { analysis, snapshot, loading, error };
}
