import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { HashRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import './App.css';
import AboutModal from './components/AboutModal';
import AppNav from './components/AppNav';
import CommandPalette from './components/CommandPalette';
import DashboardHome from './components/DashboardHome';
import ErrorBoundary from './components/ErrorBoundary';
import Icon, { Logo } from './components/Icon';
import IncidentsView from './components/IncidentsView';
import NewsFeed from './components/NewsFeed';
import PoliciesOverview from './components/PoliciesOverview';
import PolicyDetail from './components/PolicyDetail';
import PolicyLayout from './components/PolicyLayout';
import SourcesView from './components/SourcesView';
import { useNews } from './hooks/useNews';
import { usePolicySets } from './hooks/usePolicySets';
import { ReviewsProvider, useReviews } from './hooks/useReviews';
import { ToastProvider } from './hooks/useToast';
import { REPO_URL, timestampOf } from './utils/constants';
import { formatAgo, isAustralianIncident, isNew } from './utils/news';
import { reviewQueue } from './utils/reviews';
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

const isTyping = (target) =>
  target instanceof HTMLElement &&
  (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));

/** One line for the sidebar: is every source actually being read? */
function systemStatusOf(policySets, health) {
  if (policySets.length === 0) return null;
  const statuses = policySets.map((set) => health?.sources?.[set.setName]?.status || set.status || 'ok');
  const failing = statuses.filter((status) => status === 'failing').length;
  const degraded = statuses.filter((status) => status === 'degraded').length;
  const lastRun = policySets.reduce((latest, set) => Math.max(latest, timestampOf(set.last_checked)), 0);
  const detail = lastRun ? `Last checked ${formatAgo(new Date(lastRun).toISOString())}` : 'No completed check yet';
  if (failing) {
    return { level: 'critical', label: `${failing} source${failing === 1 ? '' : 's'} not being read`, detail };
  }
  if (degraded) {
    return { level: 'warning', label: `${degraded} source${degraded === 1 ? '' : 's'} had a failed read`, detail };
  }
  return { level: 'good', label: `All ${policySets.length} sources reading`, detail };
}

function AppFrame({ darkMode, setDarkMode, since }) {
  const { policySets, health, loading, error } = usePolicySets();
  const news = useNews();
  const { reviewed } = useReviews();
  const { pathname } = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);

  useEffect(() => {
    setNavOpen(false);
    window.scrollTo?.(0, 0);
  }, [pathname]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((value) => !value);
      } else if (event.key === '/' && !isTyping(event.target) && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  const policyNames = useMemo(
    () => Object.fromEntries(policySets.map((set) => [set.file_id, set.setName])),
    [policySets]
  );

  const counts = useMemo(() => {
    const items = news.feed.items || [];
    return {
      review: reviewQueue(policySets, reviewed).pending.length,
      news: since ? items.filter((item) => item.kind === 'news' && item.relevance >= 2 && isNew(item, since)).length : 0,
      incidents: since ? items.filter((item) => isAustralianIncident(item) && isNew(item, since)).length : 0,
    };
  }, [since, news.feed.items, policySets, reviewed]);

  const status = useMemo(() => systemStatusOf(policySets, health), [policySets, health]);
  const toggleTheme = useCallback(() => setDarkMode((value) => !value), [setDarkMode]);

  const actions = useMemo(
    () => [
      { label: darkMode ? 'Switch to light theme' : 'Switch to dark theme', icon: darkMode ? 'sun' : 'moon', run: toggleTheme },
      { label: 'How this dashboard works', icon: 'help', run: () => setAboutOpen(true) },
      { label: 'Suggest a source or report a problem', icon: 'external', href: `${REPO_URL}/issues/new` },
    ],
    [darkMode, toggleTheme]
  );

  const feedProps = { feed: news.feed, loading: news.loading, error: news.error, since, policyNames };
  const policyProps = { policySets, health, loading, error };

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Skip to main content</a>

      <header className="mobile-bar">
        <button type="button" className="icon-button" onClick={() => setNavOpen(true)} aria-label="Open menu">
          <Icon name="menu" />
          {counts.review > 0 && <span className="mobile-dot" aria-hidden="true" />}
        </button>
        <Link to="/" className="brand compact">
          <Logo size={26} />
          <span className="brand-name">AI Steward</span>
        </Link>
        <button type="button" className="icon-button" onClick={() => setPaletteOpen(true)} aria-label="Search">
          <Icon name="search" />
        </button>
      </header>

      <AppNav
        counts={counts}
        status={status}
        darkMode={darkMode}
        onToggleDarkMode={toggleTheme}
        onOpenSearch={() => setPaletteOpen(true)}
        onOpenAbout={() => setAboutOpen(true)}
        open={navOpen}
        onClose={() => setNavOpen(false)}
      />

      <main className="app-main" id="main-content" tabIndex={-1}>
        <Routes>
          <Route
            path="/"
            element={<DashboardHome policySets={policySets} health={health} feed={news.feed} since={since} loading={loading} />}
          />
          <Route element={<PolicyLayout {...policyProps} />}>
            <Route
              path="/policy/:fileId"
              element={<PolicyDetail policySets={policySets} health={health} feed={news.feed} since={since} />}
            />
          </Route>
          <Route path="/policies" element={<PoliciesOverview {...policyProps} />} />
          <Route path="/news" element={<NewsFeed {...feedProps} />} />
          <Route path="/incidents" element={<IncidentsView {...feedProps} />} />
          <Route path="/sources" element={<SourcesView policySets={policySets} health={health} feed={news.feed} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        policySets={policySets}
        feed={news.feed}
        actions={actions}
      />
      {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}
    </div>
  );
}

function App() {
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

  return (
    <ErrorBoundary>
      <ToastProvider>
        <ReviewsProvider>
          <HashRouter>
            <AppFrame darkMode={darkMode} setDarkMode={setDarkMode} since={since} />
          </HashRouter>
        </ReviewsProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}

export default App;
