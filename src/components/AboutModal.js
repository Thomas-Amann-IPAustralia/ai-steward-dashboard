import React, { useEffect, useRef } from 'react';
import Icon, { Logo } from './Icon';

/**
 * How the dashboard works, in plain terms first and in detail after.
 *
 * This replaces two dialogs that described an earlier version of the tool —
 * MD5 hashes over whole policy sets, a browser launched for every page, and
 * both full documents sent to the model — none of which is true any more.
 */
function AboutModal({ onClose }) {
  const closeRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    closeRef.current?.focus();
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="about-modal-title">
      <div className="modal-content" onClick={(event) => event.stopPropagation()}>
        <button type="button" className="icon-button modal-close-button" onClick={onClose} ref={closeRef} aria-label="Close dialog">
          <Icon name="x" />
        </button>
        <div className="modal-brand">
          <Logo size={36} />
          <h2 id="about-modal-title">How this works</h2>
        </div>
        <p>
          Once a day, an automated job reads every source listed on the Sources page, works out what
          genuinely changed or is genuinely new, and publishes this site. Nothing here is written by
          hand, and nothing is sent anywhere by your browser except requests for this site's own files.
        </p>

        <h3>Policy watch</h3>
        <p>
          Government AI policies and the terms of the AI services APS staff use are downloaded and
          compared, document by document, with the copy stored the day before. Most days nothing
          changes. When something does, it has to get past several checks before anyone is told:
        </p>
        <ul>
          <li><strong>Is it really the document?</strong> Error pages, “access denied” pages and pages that suddenly shrink or balloon are rejected, and the stored copy is kept.</li>
          <li><strong>Did the wording change?</strong> Differences in spacing, line breaks, quote marks, dashes, capitals or how a link is written are ignored.</li>
          <li><strong>Is it just flip-flopping?</strong> A page returning to a version already seen is recorded, not re-reported.</li>
        </ul>
        <p>
          Only then is the change — just the changed lines, not the whole document — sent to an AI
          model (Google Gemini), which summarises it, rates its priority, and is allowed to say
          “nothing material changed”. If it says so, the policy is not badged.
        </p>

        <h3>Transparency statements</h3>
        <p>
          Commonwealth agencies publish AI transparency statements saying how they use AI, and the DTA keeps a
          central register of them. The register is read for its list of agencies, so an agency joining, leaving or
          moving its statement is spotted without an AI model. Each statement is then read and compared on its own,
          through the same checks as a policy; when one changes, the model summarises what the agency now says
          differently about its AI use. These are for awareness — they never join your review queue.
        </p>
        <h3>News and AI incidents</h3>
        <p>
          News comes from Australian government sites, public-sector and technology media, overseas
          regulators and the AI providers themselves. Incidents come from the OECD AI Incidents
          Monitor. General feeds only contribute stories with AI in the headline, and live blogs
          and podcasts are left out; each item is then scored
          for relevance to APS work and, where the item says enough, given a one-line summary.
          Repeat coverage of the same event is folded into one item. Headlines always link to the
          original, which remains the authority.
        </p>

        <h3>What it can't do</h3>
        <ul>
          <li>It reads only the pages listed. Some government sites refuse automated readers; those pages are read in a real browser, or failing that from the Internet Archive's most recent copy (and marked as such), and any source not being read is flagged, never shown as “unchanged”.</li>
          <li>AI summaries and ratings can be wrong. Check the diff or the original before acting, and use 👍/👎 on an analysis to say whether it helped.</li>
          <li>It is not legal advice and not an official Australian Government product.</li>
        </ul>

        <details className="tech-details">
          <summary>Technical detail</summary>
          <ul>
            <li><strong>Pipeline:</strong> Python, run daily by GitHub Actions; results are committed to the repository and served as static files by GitHub Pages. There is no server or database.</li>
            <li><strong>Fetching:</strong> a conditional GET (ETag / Last-Modified) first; <code>requests</code> + <code>trafilatura</code> extraction; headless Chrome only for pages that need it.</li>
            <li><strong>Comparison:</strong> text is normalised and SHA-256 hashed per document; a unified diff is built only when the hash moves, and blocks that differ only typographically are set aside before diffing. Recent hashes are remembered to spot flip-flops.</li>
            <li><strong>Analysis:</strong> one Gemini call per changed policy set, constrained to a JSON schema and validated; the timestamp is stamped in code, never by the model.</li>
            <li><strong>News:</strong> RSS/Atom feeds and the OECD AIM search API, deduplicated by canonical URL, keyword-scored, then scored and summarised by the model in batches, with feed text treated strictly as untrusted data.</li>
            <li><strong>Source:</strong> see <code>BACKEND.md</code> in the project repository.</li>
          </ul>
        </details>
      </div>
    </div>
  );
}

export default AboutModal;
