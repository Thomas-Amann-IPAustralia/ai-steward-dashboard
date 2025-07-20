import React, { useState, useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import './App.css';

function App() {
  const [policySets, setPolicySets] = useState([]);
  const [selectedSet, setSelectedSet] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [snapshot, setSnapshot] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Fetch the list of policy sets from hashes.json
  useEffect(() => {
    const fetchPolicySets = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`/ai-steward-dashboard/hashes.json?v=${new Date().getTime()}`);
        if (!response.ok) {
          throw new Error(`Failed to load monitored policies. Status: ${response.status}`);
        }
        const data = await response.json();

        // Robustly process the data, filtering out any malformed or old-format entries.
        const setList = Object.keys(data)
          .map(setName => ({
            setName,
            ...data[setName]
          }))
          .filter(item => item.file_id && Array.isArray(item.urls) && item.urls.length > 0);
        
        if (setList.length === 0 && Object.keys(data).length > 0) {
            console.warn("Data in hashes.json appears to be in an old or invalid format and was filtered out.");
        }

        setPolicySets(setList);
      } catch (err) {
        console.error("Failed to load or parse hashes.json:", err);
        setError("Could not load the list of monitored policies. The data file may be missing or corrupt.");
      } finally {
        setLoading(false);
      }
    };
    fetchPolicySets();
  }, []);

  // Group policy sets by category for rendering
  const groupedSets = useMemo(() => {
    return policySets.reduce((acc, currentSet) => {
      const category = currentSet.category || 'Uncategorized';
      if (!acc[category]) {
        acc[category] = [];
      }
      acc[category].push(currentSet);
      return acc;
    }, {});
  }, [policySets]);

  // Handle selecting a policy set from the sidebar
  const handleSelectSet = async (policySet) => {
    if (selectedSet?.setName === policySet.setName) return;

    setSelectedSet(policySet);
    setLoading(true);
    setAnalysis(null);
    setSnapshot('');
    setError(null);

    try {
      const cacheBuster = `?v=${new Date().getTime()}`;
      const [analysisResponse, snapshotResponse] = await Promise.all([
        fetch(`/ai-steward-dashboard/analysis/${policySet.file_id}.json${cacheBuster}`),
        fetch(`/ai-steward-dashboard/snapshots/${policySet.file_id}.txt${cacheBuster}`)
      ]);

      if (analysisResponse.ok) {
        setAnalysis(await analysisResponse.json());
      } else {
        setAnalysis({ 
          summary: "No analysis found for this policy set.", 
          analysis: "This could be the first scan or an error might have occurred during analysis.",
          date_time: "Unknown",
          priority: "low"
        });
      }

      if (snapshotResponse.ok) {
        setSnapshot(await snapshotResponse.text());
      } else {
        setSnapshot("Could not load the content snapshot for this policy set.");
      }
      
    } catch (err) {
      console.error("Error loading policy set data:", err);
      setError(`An error occurred while loading data for ${policySet.setName}.`);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateString) => {
    if (!dateString || dateString === 'Unknown') return 'Unknown';
    try {
      return new Date(dateString).toLocaleString('en-AU', {
        timeZone: 'Australia/Sydney',
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
      });
    } catch { return dateString; }
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
          {loading && policySets.length === 0 && <div className="loading-message">Loading policies...</div>}
          {error && <div className="error-message">{error}</div>}
          
          {!loading && !error && policySets.length === 0 && (
             <div className="placeholder">No valid policies found to display. Please check the configuration.</div>
          )}

          {Object.keys(groupedSets).sort().map(category => (
            <div key={category} className="category-group">
              <h2>{category}</h2>
              <ul>
                {groupedSets[category].map(policySet => (
                  <li
                    key={policySet.setName}
                    className={selectedSet?.setName === policySet.setName ? 'active' : ''}
                    onClick={() => handleSelectSet(policySet)}
                  >
                    <div className="page-item">
                      <div className="page-title">
                        <img 
                          // **FIX**: Correctly access the 'url' property from the first item in the urls array
                          src={`https://www.google.com/s2/favicons?sz=16&domain_url=${policySet.urls[0].url}`} 
                          alt="" 
                          className="favicon"
                          onError={(e) => { e.target.style.display = 'none'; }}
                        />
                        <span>{policySet.setName}</span>
                      </div>
                      <div className="page-meta">
                        <span><strong>Last amended:</strong> {policySet.lastAmended ? formatDate(policySet.lastAmended) : 'N/A'}</span>
                        <span>Last checked: {formatDate(policySet.lastChecked)}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        
        <main className="content">
          {loading && <div className="loading-message">Loading page data...</div>}
          
          {!selectedSet && !loading && !error && (
            <div className="placeholder">
              <h2>Welcome to the AI Steward Dashboard</h2>
              <p>Select a policy set from the sidebar to view its latest analysis and content snapshot.</p>
            </div>
          )}
          
          {selectedSet && !loading && (
            <div>
              <div className="content-header">
                <h2>Analysis for: {selectedSet.setName}</h2>
                <div className="source-urls">
                  <strong>Source URL(s):</strong>
                  <ul>
                    {/* **FIX**: The 'url' variable is an object. We need to access its 'url' property. */}
                    {selectedSet.urls.map(urlObj => (
                      <li key={urlObj.url}>
                        <a href={urlObj.url} target="_blank" rel="noopener noreferrer">
                          {urlObj.url}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              
              {analysis && (
                <div className="analysis-card">
                  <div className="analysis-header">
                    <h3>Analysis Summary</h3>
                    <div className="analysis-meta">
                      <span className="priority-badge" style={{ backgroundColor: getPriorityColor(analysis.priority) }}>
                        {analysis.priority?.toUpperCase() || 'UNKNOWN'}
                      </span>
                      <span className="analysis-date">{formatDate(analysis.date_time)}</span>
                    </div>
                  </div>
                  <div className="analysis-summary"><strong>{analysis.summary}</strong></div>
                  <h4>Detailed Analysis</h4>
                  <div className="analysis-content"><ReactMarkdown>{analysis.analysis}</ReactMarkdown></div>
                </div>
              )}
              
              <hr />
              
              <h3>Aggregated Content Snapshot</h3>
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
