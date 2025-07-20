import React, { useState, useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import './App.css';

// Modal component for the "How This Works" section
const AboutModal = ({ onClose }) => {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close-button" onClick={onClose}>&times;</button>
        <h2>How the AI Steward Dashboard Works</h2>
        <p>Think of the dashboard as having three main parts that work together: <strong>The Watcher</strong>, <strong>The Analyst</strong>, and <strong>The Dashboard Website</strong>. The entire process is automated to run once every day.</p>
        
        <h3>1. The Watcher (The Python Script & Automation)</h3>
        <ul>
          <li><strong>Knows What to Watch:</strong> The system starts with a simple list (<code>policy_sets.json</code>). This list tells it exactly which government policy pages and company terms of service websites it needs to monitor.</li>
          <li><strong>Daily Check-up:</strong> Every day, an automated process kicks off on GitHub. It runs a script (<code>main.py</code>) that acts like a robot, visiting every single URL on its list.</li>
          <li><strong>Takes a "Snapshot":</strong> For each page it visits, the robot carefully copies all the relevant text and saves it as a "snapshot." It then compares this new snapshot to the one it saved from the previous day.</li>
        </ul>

        <h3>2. The Analyst (The AI Integration)</h3>
        <ul>
            <li><strong>Detects a Change:</strong> If the watcher notices <em>any</em> difference between today's snapshot and yesterday's, it flags that a change has occurred.</li>
            <li><strong>Asks the AI for Help:</strong> This is the core of the tool. The system sends both the old version and the new, changed version of the text to a powerful AI (Google's Gemini).</li>
            <li><strong>Gets a Human-Friendly Summary:</strong> It asks the AI to do two things:
                <ul>
                    <li>Write a clear, simple summary of exactly what changed.</li>
                    <li>Analyse the importance of the change and assign a priority level (e.g., <code>Critical</code>, <code>High</code>, <code>Low</code>).</li>
                </ul>
            </li>
            <li><strong>Saves the Analysis:</strong> The AI's summary and priority rating are saved. The new snapshot also replaces the old one, ready for the next day's comparison.</li>
        </ul>

        <h3>3. The Dashboard Website (The React App)</h3>
        <ul>
            <li><strong>Presents the Information:</strong> This is the part you see and interact with. It's a simple website (<code>App.js</code>) that reads all the saved snapshots and AI-generated summaries.</li>
            <li><strong>Easy Navigation:</strong> The dashboard displays a clean list of all the policies being tracked. You can click on any of them.</li>
            <li><strong>Shows You What Matters:</strong> When you select a policy, the dashboard instantly shows you the AI's latest analysis, including the priority and a summary of the most recent changes. You can also view the full text snapshot that the watcher saved.</li>
        </ul>
        
        <p>In short, the system automatically <strong>watches</strong> key websites, uses <strong>AI to analyze</strong> any changes it finds, and presents those findings on a simple <strong>dashboard</strong> for you to review.</p>
      </div>
    </div>
  );
};


function App() {
  const [policySets, setPolicySets] = useState([]);
  const [selectedSet, setSelectedSet] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [snapshot, setSnapshot] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isAboutModalOpen, setIsAboutModalOpen] = useState(false); // State for the modal

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
      {isAboutModalOpen && <AboutModal onClose={() => setIsAboutModalOpen(false)} />}
      
      <header className="App-header">
        <div className="header-content">
          <h1>The Vigilant Bureaucrat</h1>
          <p>Tracking AI Policy and Terms of Service Updates for Australian Public Servants - IM2025</p>
        </div>
        <button className="about-button" onClick={() => setIsAboutModalOpen(true)}>
          How This Works
        </button>
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
              <p>Click the "How This Works" button in the top right to learn more about this tool.</p>
            </div>
          )}
          
          {selectedSet && !loading && (
            <div>
              <div className="content-header">
                <h2>Analysis for: {selectedSet.setName}</h2>
                <div className="source-urls">
                  <strong>Source URL(s):</strong>
                  <ul>
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
