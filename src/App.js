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

  // Fetch the list of URLs from the hashes.json file in the public folder.
  // This runs once when the component mounts.
  useEffect(() => {
    const fetchPages = async () => {
      setLoading(true);
      setError(null);
      try {
        // Fetch from a relative path. On GitHub Pages, this will be relative to the domain root.
        const response = await fetch(`/ai-steward-dashboard/hashes.json`);
        
        if (!response.ok) {
          throw new Error(`Failed to load monitored pages. Status: ${response.status}`);
        }

        const data = await response.json();
        
        const pageList = Object.keys(data).map(url => ({
          url,
          hash: data[url].hash,
          lastChecked: data[url].last_checked,
          // Generate a consistent filename based on the URL's MD5 hash
          filename: md5(url) 
        }));
        
        setPages(pageList);
      } catch (err) {
        console.error("Failed to load hashes.json:", err);
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchPages();
  }, []); // Empty dependency array means this runs only once.

  // This function is called when a user clicks on a page in the sidebar.
  const handleSelectPage = async (page) => {
    setSelectedPage(page);
    setLoading(true);
    setAnalysis(null);
    setSnapshot('');
    setError(null);

    try {
      // Fetch analysis and snapshot data for the selected page in parallel.
      const [analysisResponse, snapshotResponse] = await Promise.all([
        fetch(`/ai-steward-dashboard/analysis/${page.filename}.json`),
        fetch(`/ai-steward-dashboard/snapshots/${page.filename}.txt`)
      ]);

      if (analysisResponse.ok) {
        const analysisData = await analysisResponse.json();
        setAnalysis(analysisData);
      } else {
        // Provide a default message if analysis is not found.
        setAnalysis({ 
          summary: "No analysis found.", 
          analysis: "This might be the first time this page has been scanned, or an error occurred.",
          date_time: "Unknown",
          priority: "low"
        });
      }

      if (snapshotResponse.ok) {
        const snapshotData = await snapshotResponse.text();
        setSnapshot(snapshotData);
      } else {
        setSnapshot("Could not load the content snapshot.");
      }
      
    } catch (err) {
      console.error("Error loading page data:", err);
      setError(`Error loading data for ${page.url}: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Helper function to format date strings nicely for an Australian audience.
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
      // Fallback for invalid date formats.
      return dateString;
    }
  };

  // Determines the color of the priority badge based on the priority level.
  const getPriorityColor = (priority) => {
    switch (priority?.toLowerCase()) {
      case 'critical': return '#dc2626'; // Red
      case 'high': return '#ea580c';     // Orange
      case 'medium': return '#d97706';   // Amber
      case 'low': return '#16a34a';      // Green
      default: return '#6b7280';         // Gray
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
          
          {loading && pages.length === 0 && (
            <div className="loading-message">Loading monitored pages...</div>
          )}

          {error && pages.length === 0 && (
            <div className="error-message">{error}</div>
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
          {loading && (
            <div className="loading-message">Loading page data...</div>
          )}
          
          {error && (
            <div className="error-message">{error}</div>
          )}
          
          {!selectedPage && !loading && !error && (
            <div className="placeholder">
              <h2>Welcome to the AI Steward Dashboard</h2>
              <p>Select a page from the left sidebar to view its latest analysis and content snapshot.</p>
            </div>
          )}
          
          {selectedPage && !loading && !error && (
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
