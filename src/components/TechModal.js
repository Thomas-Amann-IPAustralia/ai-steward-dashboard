import React, { useEffect, useRef } from 'react';

function TechModal({ onClose }) {
  const closeRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    closeRef.current?.focus();
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="tech-modal-title">
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close-button" onClick={onClose} ref={closeRef} aria-label="Close dialog">&times;</button>
        <h2 id="tech-modal-title">Application Architecture & Process Flow</h2>
        <p>This application operates via a serverless, GitOps-centric architecture. The entire process is orchestrated through GitHub Actions and leverages a combination of Python for backend processing and React for the frontend user interface.</p>

        <h3>1. CI/CD & Automation (GitHub Actions)</h3>
        <ul>
          <li><strong>Workflow Trigger:</strong> The process is defined in <code>.github/workflows/update_checker.yml</code>. It runs on a daily cron schedule (<code>0 0 * * *</code>) and is also triggered on pushes to the <code>main</code> branch affecting key files.</li>
          <li><strong>Environment:</strong> The workflow executes on an <code>ubuntu-latest</code> runner, setting up Node.js and Python environments with cached dependencies for efficiency.</li>
        </ul>

        <h3>2. Backend Scraper & Data Processor (<code>main.py</code>)</h3>
        <ul>
          <li><strong>Technology:</strong> Python, <code>Selenium</code> with <code>selenium-stealth</code> to evade bot-detection, <code>webdriver-manager</code> for Chrome driver management, and <code>BeautifulSoup4</code> for HTML parsing.</li>
          <li><strong>Process:</strong>
            <ol>
              <li>The script loads target URLs from <code>policy_sets.json</code>.</li>
              <li>For each policy set, it initializes a headless Chrome instance and navigates to the specified URLs.</li>
              <li>It scrapes the page content, which is then parsed by BeautifulSoup to remove irrelevant HTML tags (e.g., <code>&lt;nav&gt;</code>, <code>&lt;footer&gt;</code>), isolating the core text.</li>
              <li>The cleaned text from all URLs in a set is aggregated, and an MD5 hash is generated from this content.</li>
            </ol>
          </li>
        </ul>

        <h3>3. State Management & Diffing (<code>hashes.json</code>)</h3>
        <ul>
          <li>The script compares the newly generated MD5 hash against the previous hash stored in <code>hashes.json</code> for that policy set.</li>
          <li><strong>No Change:</strong> If hashes match, only the <code>last_checked</code> timestamp is updated.</li>
          <li><strong>Change Detected:</strong> If hashes differ, it proceeds to the analysis stage, updating the <code>last_amended</code> timestamp.</li>
        </ul>

        <h3>4. AI Analysis (Google Gemini API)</h3>
        <ul>
          <li><strong>Technology:</strong> The <code>google-generativeai</code> Python library for the Gemini 1.5 Flash model.</li>
          <li><strong>Process:</strong> When a change is detected, the old content (from the prior snapshot) and the new content are sent to the Gemini API. A carefully engineered prompt instructs the model to return a structured JSON object containing an <code>analysis</code>, a <code>summary</code>, and a <code>priority</code> rating.</li>
        </ul>

        <h3>5. Data Persistence & GitOps</h3>
        <ul>
          <li>The Python script writes the generated data to the file system: new text content to <code>/snapshots</code>, AI analysis to <code>/analysis</code>, and updates <code>hashes.json</code>.</li>
          <li>The GitHub Actions workflow then commits these changes directly back to the repository. This Git-based, "state-in-repo" approach provides a complete, auditable history of all content changes and analyses.</li>
        </ul>

        <h3>6. Frontend & Deployment (React & GitHub Pages)</h3>
        <ul>
          <li><strong>Technology:</strong> A standard <code>create-react-app</code> build, using <code>ReactMarkdown</code> to render the analysis content.</li>
          <li><strong>Process:</strong>
            <ol>
              <li>The React app is a fully static single-page application. On load, it fetches <code>hashes.json</code> to populate the sidebar.</li>
              <li>When a user selects a policy, it dynamically fetches the relevant static files to display the details.</li>
              <li>After the backend script commits any data changes, the GitHub Actions workflow triggers a new React build and deploys the resulting static files to GitHub Pages.</li>
            </ol>
          </li>
        </ul>
      </div>
    </div>
  );
}

export default TechModal;
