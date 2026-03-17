import React, { useEffect, useRef } from 'react';

function AboutModal({ onClose }) {
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
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="about-modal-title">
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close-button" onClick={onClose} ref={closeRef} aria-label="Close dialog">&times;</button>
        <h2 id="about-modal-title">How the AI Steward Dashboard Works</h2>
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
          <li><strong>Presents the Information:</strong> This is the part you see and interact with. It's a simple website that reads all the saved snapshots and AI-generated summaries.</li>
          <li><strong>Easy Navigation:</strong> The dashboard displays a clean list of all the policies being tracked. You can click on any of them.</li>
          <li><strong>Shows You What Matters:</strong> When you select a policy, the dashboard instantly shows you the AI's latest analysis, including the priority and a summary of the most recent changes. You can also view the full text snapshot that the watcher saved.</li>
        </ul>

        <p>In short, the system automatically <strong>watches</strong> key websites, uses <strong>AI to analyze</strong> any changes it finds, and presents those findings on a simple <strong>dashboard</strong> for you to review.</p>
      </div>
    </div>
  );
}

export default AboutModal;
