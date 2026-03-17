import { useState, useEffect, useMemo } from 'react';
import { BASE_URL } from '../utils/constants';

export function usePolicySets() {
  const [policySets, setPolicySets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchPolicySets = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${BASE_URL}/hashes.json?v=${Date.now()}`);
        if (!response.ok) {
          throw new Error(`Failed to load monitored policies. Status: ${response.status}`);
        }
        const data = await response.json();

        const setList = Object.keys(data)
          .map(setName => ({ setName, ...data[setName] }))
          .filter(item => item.file_id && Array.isArray(item.urls) && item.urls.length > 0);

        if (setList.length === 0 && Object.keys(data).length > 0) {
          console.warn('Data in hashes.json appears to be in an old or invalid format.');
        }

        setPolicySets(setList);
      } catch (err) {
        console.error('Failed to load or parse hashes.json:', err);
        setError('Could not load the list of monitored policies. The data file may be missing or corrupt.');
      } finally {
        setLoading(false);
      }
    };
    fetchPolicySets();
  }, []);

  const groupedSets = useMemo(() => {
    return policySets.reduce((acc, set) => {
      const category = set.category || 'Uncategorized';
      if (!acc[category]) acc[category] = [];
      acc[category].push(set);
      return acc;
    }, {});
  }, [policySets]);

  return { policySets, groupedSets, loading, error };
}
