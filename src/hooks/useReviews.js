import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { loadReviewed, saveReviewed, setReviewed } from '../utils/reviews';

const ReviewsContext = createContext({ reviewed: {}, markReviewed: () => {} });

const safeStorage = () => {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

/** Holds which policy changes this browser has marked as reviewed. */
export function ReviewsProvider({ children }) {
  const [reviewed, setState] = useState(() => loadReviewed(safeStorage()));

  const markReviewed = useCallback((set, done = true) => {
    setState((current) => saveReviewed(safeStorage(), setReviewed(current, set, done)));
  }, []);

  const value = useMemo(() => ({ reviewed, markReviewed }), [reviewed, markReviewed]);
  return <ReviewsContext.Provider value={value}>{children}</ReviewsContext.Provider>;
}

export const useReviews = () => useContext(ReviewsContext);
