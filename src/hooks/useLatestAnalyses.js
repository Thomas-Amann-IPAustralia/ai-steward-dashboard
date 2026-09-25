import { useEffect, useMemo, useState } from 'react';
import { BASE_URL, fetchWithTimeout } from '../utils/constants';

const cache = {};
const inflight = {};

const load = (fileId) => {
  if (!inflight[fileId]) {
    inflight[fileId] = fetchWithTimeout(`${BASE_URL}/analysis/${fileId}.json?v=${Date.now()}`)
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null)
      .then((data) => {
        cache[fileId] = data
          ? { summary: data.summary || '', date_time: data.date_time || '', verdict: data.verdict || null }
          : null;
        return cache[fileId];
      });
  }
  return inflight[fileId];
};

/**
 * The one-line summary of each set's latest analysis, from analysis/*.json.
 *
 * hashes.json only carries a summary for some changes, so the review queue
 * and the policy cards would otherwise say "no summary" for a change the
 * model did summarise. Supplementary like health.json: a file that fails to
 * load just leaves that card without a summary. Only the summary and its
 * timestamp are kept, so a card can check it describes the change it shows.
 */
export function useLatestAnalyses(fileIds) {
  const key = fileIds.join('|');
  const ids = useMemo(() => (key ? key.split('|') : []), [key]);
  const [loaded, setLoaded] = useState(() => Object.fromEntries(ids.filter((id) => id in cache).map((id) => [id, cache[id]])));

  useEffect(() => {
    let active = true;
    Promise.all(ids.map((id) => (id in cache ? cache[id] : load(id)))).then((results) => {
      if (active) setLoaded(Object.fromEntries(ids.map((id, index) => [id, results[index]])));
    });
    return () => {
      active = false;
    };
  }, [ids]);

  return loaded;
}
