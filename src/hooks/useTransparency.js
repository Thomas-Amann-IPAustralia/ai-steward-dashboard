import { useEffect, useState } from 'react';
import { BASE_URL, fetchWithTimeout } from '../utils/constants';

let cached = null;
let inflight = null;

const EMPTY = { register: null, statements: [], events: [], generated_at: null };

const loadJson = async (path) => {
  const response = await fetchWithTimeout(`${BASE_URL}/${path}?v=${Date.now()}`);
  if (!response.ok) throw new Error(`${path}: status ${response.status}`);
  return response.json();
};

/**
 * Loads transparency/statements.json (the register and every statement's
 * state) and transparency/events.json (who joined, left or moved, and what
 * changed).
 *
 * Supplementary in the same way the news feed is: if the statements are
 * missing the tab says so and nothing else is affected, and missing events
 * only empty the activity list. Fetched once per page load and shared.
 */
export function useTransparency() {
  const [state, setState] = useState(() =>
    cached ? { data: cached, loading: false, error: null } : { data: EMPTY, loading: true, error: null }
  );

  useEffect(() => {
    if (cached) return undefined;
    let active = true;

    if (!inflight) {
      inflight = Promise.all([
        loadJson('transparency/statements.json'),
        loadJson('transparency/events.json').catch((err) => {
          console.warn('transparency/events.json unavailable:', err);
          return [];
        }),
      ])
        .then(([statements, events]) => {
          cached = {
            ...EMPTY,
            ...statements,
            statements: Array.isArray(statements?.statements) ? statements.statements : [],
            events: Array.isArray(events) ? events : [],
          };
          return cached;
        })
        .finally(() => {
          inflight = null;
        });
    }

    inflight
      .then((data) => {
        if (active) setState({ data, loading: false, error: null });
      })
      .catch((err) => {
        console.warn('transparency/statements.json unavailable:', err);
        if (active) {
          setState({ data: EMPTY, loading: false, error: 'The transparency statements have not been read yet.' });
        }
      });

    return () => {
      active = false;
    };
  }, []);

  return state;
}
