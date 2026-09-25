import React from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import Icon, { Logo } from './Icon';

const NAV = [
  { to: '/', label: 'Overview', icon: 'overview', end: true },
  { to: '/policies', label: 'Policy watch', icon: 'policy', countKey: 'review', section: /^\/polic(y|ies)\b/ },
  { to: '/news', label: 'News', icon: 'news', countKey: 'news' },
  { to: '/incidents', label: 'AI incidents', icon: 'incident', countKey: 'incidents' },
  { to: '/transparency', label: 'Transparency', icon: 'eye', countKey: 'transparency' },
  { to: '/sources', label: 'Sources', icon: 'sources' },
];

const COUNT_LABELS = {
  review: (n) => `${n} policy change${n === 1 ? '' : 's'} to review`,
  news: (n) => `${n} new since your last visit`,
  incidents: (n) => `${n} new since your last visit`,
  transparency: (n) => `${n} statement update${n === 1 ? '' : 's'} since your last visit`,
};

/**
 * The app's navigation: the sections, a search launcher, and a live status
 * line saying whether every source is actually being read. Policy watch
 * carries the only count that asks for action — changes still to review —
 * so it is styled as one; the other sections only say what is new.
 */
function AppNav({ counts = {}, status, darkMode, onToggleDarkMode, onOpenSearch, onOpenAbout, open, onClose }) {
  const { pathname } = useLocation();
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '');

  return (
    <>
      <div className={`nav-scrim${open ? ' open' : ''}`} onClick={onClose} aria-hidden="true" />
      <aside className={`app-nav${open ? ' open' : ''}`} aria-label="Main">
        <div className="app-nav-top">
          <Link to="/" className="brand" aria-label="AI Steward — overview">
            <Logo size={30} />
            <span className="brand-text">
              <span className="brand-name">AI Steward</span>
              <span className="brand-sub">Policy &amp; AI watch for the APS</span>
            </span>
          </Link>
          <button type="button" className="icon-button nav-close" onClick={onClose} aria-label="Close menu">
            <Icon name="x" />
          </button>
        </div>

        <button type="button" className="search-launcher" onClick={onOpenSearch}>
          <Icon name="search" size={16} />
          <span>Search…</span>
          <kbd>{isMac ? '⌘' : 'Ctrl'} K</kbd>
        </button>

        <nav className="nav-list" aria-label="Sections">
          {NAV.map((item) => {
            const count = item.countKey ? counts[item.countKey] || 0 : 0;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => `nav-item${isActive || item.section?.test(pathname) ? ' active' : ''}`}
              >
                <Icon name={item.icon} size={18} />
                <span className="nav-label">{item.label}</span>
                {count > 0 && (
                  <span
                    className={`nav-count${item.countKey === 'review' ? ' action' : ''}`}
                    title={COUNT_LABELS[item.countKey](count)}
                  >
                    {count}
                    <span className="visually-hidden"> — {COUNT_LABELS[item.countKey](count)}</span>
                  </span>
                )}
              </NavLink>
            );
          })}
        </nav>

        <div className="app-nav-foot">
          {status && (
            <Link to="/sources" className={`system-status level-${status.level}`}>
              <span className="status-beacon" aria-hidden="true" />
              <span className="system-status-text">
                <strong>{status.label}</strong>
                <span>{status.detail}</span>
              </span>
            </Link>
          )}
          <div className="nav-actions">
            <button type="button" className="nav-action" onClick={onOpenAbout}>
              <Icon name="help" size={16} />
              How it works
            </button>
            <button
              type="button"
              className="icon-button"
              onClick={onToggleDarkMode}
              aria-label={darkMode ? 'Switch to light theme' : 'Switch to dark theme'}
              title={darkMode ? 'Light theme' : 'Dark theme'}
            >
              <Icon name={darkMode ? 'sun' : 'moon'} size={17} />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

export default AppNav;
