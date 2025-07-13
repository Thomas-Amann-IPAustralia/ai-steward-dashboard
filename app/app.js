import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import './App.css';

// Hashing function to get the filename (must match Python's)
import md5 from 'md5';

function App() {
  const [pages, setPages] = useState([]);
  const [selectedPage, setSelectedPage] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [snapshot, setSnapshot] = useState('');
  const [loading, setLoading] = useState(false);

  // Base URL for fetching data from the GitHub repo
  const baseUrl = `https://raw.githubusercontent.com/Thomas-Amann-IPAustralia/ai-steward-dashboard/main`;

  useEffect(() => {
    // Fetch the list of URLs from hashes.json
    fetch(`${baseUrl}/hashes.json?cachebust=${new Date().getTime()}`)
      .then(res => res.json())
      .then(data => {
        const pageList = Object.keys(data).map(url => ({
          url,
          hash: data[url],
          filename: md5(url)
        }));
        setPages(pageList);
      })
      .catch(err => console.error("Failed to load hashes:", err));
  }, [baseUrl]);

  const handleSelectPage = (page) => {
    setSelectedPage(page);
    setLoading(true);
    setAnalysis(null);
    setSnapshot('');

    // Fetch analysis data
    fetch(`${baseUrl}/analysis/${page.filename}.json?cachebust=${new Date().getTime()}`)
      .then(res => res.json())
      .then(data => setAnalysis(data))
      .catch(() => setAnalysis({ summary: "No analysis found.", analysis: "This may be the first time this page has been scanned." }));

    // Fetch snapshot data
    fetch(`${baseUrl}/snapshots/${page.filename}.txt?cachebust=${new Date().getTime()}`)
      .then(res => res.text())
      .then(data => setSnapshot(data))
      .catch(() => setSnapshot("Could not load snapshot."))
      .finally(() => setLoading(false));
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>AI Steward Dashboard</h1>
        <p>Tracking AI Policy and Terms of Service Updates for Australian Public Servants</p>
      </header>
      <div className="container">
        <nav className="sidebar">
          <h2>Monitored Pages</h2>
          <ul>
            {pages.map(page => (
              <li
                key={page.url}
                className={selectedPage?.url === page.url ? 'active' : ''}
                onClick={() => handleSelectPage(page)}
              >
                {page.url}
              </li>
            ))}
          </ul>
        </nav>
        <main className="content">
          {loading && <p>Loading...</p>}
          {!selectedPage && !loading && (
            <div className="placeholder">
              <h2>Welcome</h2>
              <p>Select a page from the left to view its latest analysis and content snapshot.</p>
            </div>
          )}
          {selectedPage && !loading && (
            <div>
              <h2>Analysis for <a href={selectedPage.url} target="_blank" rel="noopener noreferrer">{selectedPage.url}</a></h2>
              {analysis && (
                <div className="analysis-card">
                  <h3>Summary</h3>
                  <p><strong>{analysis.summary}</strong></p>
                  <h3>Detailed Analysis</h3>
                  <ReactMarkdown>{analysis.analysis}</ReactMarkdown>
                </div>
              )}
              <hr />
              <h2>Current Content Snapshot</h2>
              <pre className="snapshot-content">{snapshot}</pre>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
