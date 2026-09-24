import React, { useEffect, useMemo, useState } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import './App.css';
import DashboardHome from './components/DashboardHome';
import ErrorBoundary from './components/ErrorBoundary';
import Header from './components/Header';
import IncidentsView from './components/IncidentsView';
import NewsFeed from './components/NewsFeed';
import PoliciesOverview from './components/PoliciesOverview';
import PolicyDetail from './components/PolicyDetail';
import PolicyLayout from './components/PolicyLayout';
import SourcesView from './components/SourcesView';
import { useNews } from './hooks/useNews';
import { usePolicySets } from './hooks/usePolicySets';
import { timestampOf } from './utils/constants';
import { isAustralianIncident, isNew } from './utils/news';
import { recordVisit } from './utils/visits';

const initialDarkMode = () => {
  try {
    const stored = localStorage.getItem('darkMode');
    if (stored !== null) return stored === 'true';
  } catch {
    // Storage blocked; fall through to the system preference.
  }
  return Boolean(window.matchMedia?.('(prefers-color-scheme: dark)').matches);
};

const safeStorage = () => {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

function App() {
  const { policySets, health, loading, error } = usePolicySets();
  const news = useNews();
  const [darkMode, setDarkMode] = useState(initialDarkMode);
  // Read once per page load: the start of the previous visit, or null.
  const [since] = useState(() => {
    const storage = safeStorage();
    return storage ? recordVisit(storage) : null;
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light');
    try {
      localStorage.setItem('darkMode', darkMode);
    } catch {
      // Not remembered; the toggle still works for this visit.
    }
  }, [darkMode]);

  const policyNames = useMemo(
    () => Object.fromEntries(policySets.map((set) => [set.file_id, set.setName])),
    [policySets]
  );

  const newCounts = useMemo(() => {
    if (!since) return {};
    const items = news.feed.items || [];
    return {
      policies: policySets.filter((set) => timestampOf(set.last_amended) > since && set.last_verdict !== 'no_material_change').length,
      news: items.filter((item) => item.kind === 'news' && item.relevance >= 2 && isNew(item, since)).length,
      incidents: items.filter((item) => isAustralianIncident(item) && isNew(item, since)).length,
    };
  }, [since, news.feed.items, policySets]);

  const feedProps = { feed: news.feed, loading: news.loading, error: news.error, since, policyNames };
  const policyProps = { policySets, health, loading, error };

  return (
    <ErrorBoundary>
      <HashRouter>
        <div className="App">
          <a href="#main-content" className="skip-link">Skip to main content</a>
          <Header
            darkMode={darkMode}
            onToggleDarkMode={() => setDarkMode((value) => !value)}
            newCounts={newCounts}
          />
          <main className="content" id="main-content">
            <Routes>
              <Route
                path="/"
                element={<DashboardHome policySets={policySets} health={health} feed={news.feed} since={since} />}
              />
              <Route element={<PolicyLayout {...policyProps} />}>
                <Route path="/policies" element={<PoliciesOverview {...policyProps} />} />
                <Route
                  path="/policy/:fileId"
                  element={<PolicyDetail policySets={policySets} health={health} feed={news.feed} since={since} />}
                />
              </Route>
              <Route path="/news" element={<NewsFeed {...feedProps} />} />
              <Route path="/incidents" element={<IncidentsView {...feedProps} />} />
              <Route path="/sources" element={<SourcesView policySets={policySets} health={health} feed={news.feed} />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </HashRouter>
    </ErrorBoundary>
  );
}

export default App;
