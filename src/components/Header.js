import React, { useState } from 'react';
import AboutModal from './AboutModal';
import TechModal from './TechModal';

function Header({ darkMode, onToggleDarkMode }) {
  const [isAboutModalOpen, setIsAboutModalOpen] = useState(false);
  const [isTechModalOpen, setIsTechModalOpen] = useState(false);

  return (
    <>
      {isAboutModalOpen && <AboutModal onClose={() => setIsAboutModalOpen(false)} />}
      {isTechModalOpen && <TechModal onClose={() => setIsTechModalOpen(false)} />}

      <header className="App-header">
        <div className="header-content">
          <h1>Vigilant Bureaucrat Dashboard</h1>
          <p>Tracking AI Policy and Terms of Service Updates for Australian Public Servants</p>
        </div>
        <div className="header-buttons">
          <button className="about-button" onClick={() => setIsAboutModalOpen(true)}>
            How This Works
          </button>
          <button className="about-button tech-button" onClick={() => setIsTechModalOpen(true)}>
            How This Works (but for nerds)
          </button>
          <button
            className="about-button dark-mode-toggle"
            onClick={onToggleDarkMode}
            aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {darkMode ? 'Light Mode' : 'Dark Mode'}
          </button>
        </div>
      </header>
    </>
  );
}

export default Header;
