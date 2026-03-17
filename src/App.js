import React, { useState, useEffect } from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
import './App.css';
import Header from './components/Header';
import Sidebar from './components/Sidebar';
import DashboardHome from './components/DashboardHome';
import PolicyDetail from './components/PolicyDetail';
import ErrorBoundary from './components/ErrorBoundary';
import { usePolicySets } from './hooks/usePolicySets';

function App() {
  const { policySets, loading, error } = usePolicySets();
  const [darkMode, setDarkMode] = useState(
    () => localStorage.getItem('darkMode') === 'true'
  );

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light');
    localStorage.setItem('darkMode', darkMode);
  }, [darkMode]);

  return (
    <ErrorBoundary>
      <HashRouter>
        <div className="App">
          <a href="#main-content" className="skip-link">Skip to main content</a>
          <Header darkMode={darkMode} onToggleDarkMode={() => setDarkMode(!darkMode)} />
          <div className="container">
            <Sidebar policySets={policySets} loading={loading} error={error} />
            <main className="content" id="main-content">
              <Routes>
                <Route path="/" element={<DashboardHome policySets={policySets} />} />
                <Route path="/policy/:fileId" element={<PolicyDetail policySets={policySets} />} />
              </Routes>
            </main>
          </div>
        </div>
      </HashRouter>
    </ErrorBoundary>
  );
}

export default App;
