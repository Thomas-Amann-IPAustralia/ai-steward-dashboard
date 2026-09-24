import React, { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import AboutModal from './AboutModal';

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/policies', label: 'Policy watch', countKey: 'policies', section: /^\/polic(y|ies)\b/ },
  { to: '/news', label: 'News', countKey: 'news' },
  { to: '/incidents', label: 'AI incidents', countKey: 'incidents' },
  { to: '/sources', label: 'Sources' },
];

function Header({ darkMode, onToggleDarkMode, newCounts = {} }) {
  const [aboutOpen, setAboutOpen] = useState(false);
  const { pathname } = useLocation();

  return (
    <>
      {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}

      <header className="App-header">
        <div className="header-top">
          <div className="header-content">
            <h1>Vigilant Bureaucrat Dashboard</h1>
            <p>AI policy, news and incidents for Australian Public Servants — checked daily</p>
          </div>
          <div className="header-buttons">
            <button type="button" className="about-button" onClick={() => setAboutOpen(true)}>
              How it works
            </button>
            <button
              type="button"
              className="about-button dark-mode-toggle"
              onClick={onToggleDarkMode}
              aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {darkMode ? 'Light' : 'Dark'}
            </button>
          </div>
        </div>
        <nav className="primary-nav" aria-label="Sections">
          {NAV.map((item) => {
            const count = item.countKey ? newCounts[item.countKey] : 0;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                // A single policy's page belongs to the Policy watch section.
                className={({ isActive }) =>
                  `nav-link${isActive || item.section?.test(pathname) ? ' active' : ''}`
                }
              >
                {item.label}
                {count > 0 && (
                  <span className="nav-count" aria-label={`${count} new since your last visit`}>
                    {count}
                  </span>
                )}
              </NavLink>
            );
          })}
        </nav>
      </header>
    </>
  );
}

export default Header;
