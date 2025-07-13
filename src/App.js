import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import './App.css';
import md5 from 'md5';

function App() {
  const [pages, setPages] = useState([]);
  const [selectedPage, setSelectedPage] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [snapshot, setSnapshot] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Base URL for fetching data from the GitHub repo
  const baseUrl = process.env.NODE_ENV === 'development' 
    ? 'https://raw.githubusercontent.com/Thomas-Amann-IPAustralia/ai-steward-dashboard/main'
    : 'https://raw.githubusercontent.com/Thomas-Amann-IPAustralia/ai-steward-dashboard/main';

  useEffect(() => {
    // Fetch the list of URLs from hashes.json
    const fetchPages = async () => {
      try {
        setLoading(true);
        setError(null);
        
        const response = await fetch(`${baseUrl}/hashes.json?cachebust=${new Date().getTime()}`);
        
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        const pageList = Object.keys(data).map(url => ({
          url,
          hash: data[url].hash || data[url], // Handle both old and new format
          lastChecked: data[url].last_checked || 'Unknown',
          filename: md5(url)
        }));
        
        setPages(pageList);
      } catch (err) {
        console.error("Failed to load hashes:", err);
        setError(`Failed to load monitored pages: ${err.message}`);
      } finally {
        setLoading(false);
      }
    };

    fetchPages();
  }, [baseUrl]);

  const handleSelectPage = async (page) => {
    setSelectedPage(page);
    setLoading(true);
    setAnalysis(null);
    setSnapshot('');
    setError(null);

    try {
      // Fetch analysis data
      const analysisResponse = await fetch(`${baseUrl}/analysis/${page.filename}.json?cachebust=${new Date().getTime()}`);
      
      if (analysisResponse.ok) {
        const analysisData = await analysisResponse.json();
        setAnalysis(analysisData);
      } else {
        setAnalysis({ 
          summary: "No analysis found.", 
          analysis: "This may be the first time this page has been scanned.",
          date_time: "Unknown",
          priority: "low"
        });
      }

      // Fetch snapshot data
      const snapshotResponse = await fetch(`${baseUrl}/snapshots/${page.filename}.txt?cachebust=${new Date().getTime()}`);
      
      if (snapshotResponse.ok) {
        const snapshotData = await snapshotResponse.text();
        setSnapshot(snapshotData);
      } else {
        setSnapshot("Could not load snapshot. This may be the first time this page has been scanned.");
      }
      
    } catch (err) {
      console.error("Error loading page data:", err);
      setError(`Error loading page data: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateString) => {
    if (!dateString || dateString === 'Unknown') return 'Unknown';
    try {
      return new Date(dateString).toLocaleString('en-AU', {
        timeZone: 'Australia/Sydney',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateString;
    }
  };

  const getPriorityColor = (priority) => {
    switch (priority?.toLowerCase()) {
      case 'critical': return '#dc2626';
      case 'high': return '#ea580c';
      case 'medium': return '#d97706';
      case 'low': return '#16a34a';
      default: return '#6b7280';
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>AI Steward Dashboard</h1>
        <p>Tracking AI Policy and Terms of Service Updates for Australian Public Servants</p>
      </header>
      
      <div className="container">
        <nav className="sidebar">
          <h2>Monitored Pages ({pages.length})</h2>
          
          {error && (
            <div className="error-message">
              {error}
            </div>
          )}
          
          {loading && !selectedPage && (
            <div className="loading-message">
              Loading monitored pages...
            </div>
          )}
          
          <ul>
            {pages.map(page => (
              <li
                key={page.url}
                className={selectedPage?.url === page.url ? 'active' : ''}
                onClick={() => handleSelectPage(page)}
              >
                <div className="page-item">
                  <div className="page-url">{page.url}</div>
                  <div className="page-meta">
                    Last checked: {formatDate(page.lastChecked)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </nav>
        
        <main className="content">
          {loading && selectedPage && (
            <div className="loading-message">
              Loading page data...
            </div>
          )}
          
          {error && selectedPage && (
            <div className="error-message">
              {error}
            </div>
          )}
          
          {!selectedPage && !loading && (
            <div className="placeholder">
              <h2>Welcome to the AI Steward Dashboard</h2>
              <p>Select a page from the left sidebar to view its latest analysis and content snapshot.</p>
              <p>This dashboard monitors changes to AI policies and terms of service relevant to Australian public servants.</p>
            </div>
          )}
          
          {selectedPage && !loading && (
            <div>
              <h2>
                Analysis for{' '}
                <a href={selectedPage.url} target="_blank" rel="noopener noreferrer">
                  {selectedPage.url}
                </a>
              </h2>
              
              {analysis && (
                <div className="analysis-card">
                  <div className="analysis-header">
                    <h3>Analysis Summary</h3>
                    <div className="analysis-meta">
                      <span 
                        className="priority-badge"
                        style={{ backgroundColor: getPriorityColor(analysis.priority) }}
                      >
                        {analysis.priority?.toUpperCase() || 'UNKNOWN'}
                      </span>
                      <span className="analysis-date">
                        {formatDate(analysis.date_time)}
                      </span>
                    </div>
                  </div>
                  
                  <div className="analysis-summary">
                    <strong>{analysis.summary}</strong>
                  </div>
                  
                  <h4>Detailed Analysis</h4>
                  <div className="analysis-content">
                    <ReactMarkdown>{analysis.analysis}</ReactMarkdown>
                  </div>
                </div>
              )}
              
              <hr />
              
              <h3>Current Content Snapshot</h3>
              <div className="snapshot-container">
                <pre className="snapshot-content">{snapshot}</pre>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
