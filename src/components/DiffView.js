import React, { useMemo, useState } from 'react';

/**
 * Renders the unified diff that produced an analysis.
 *
 * The detail page used to lead with a <pre> dump of the entire snapshot, which
 * is the least useful element on the page — nobody reads 97 kB of terms of
 * service looking for the sentence that moved. The diff is already collapsed
 * to changed hunks with a few lines of context, which is exactly the view a
 * steward wants.
 */

const parseDiff = (text) => {
  const files = [];
  let current = null;
  let hunk = null;

  const pushHunk = () => {
    if (hunk && current) current.hunks.push(hunk);
    hunk = null;
  };

  text.split('\n').forEach((line) => {
    if (line.startsWith('=====')) {
      pushHunk();
      current = { label: line.replace(/=/g, '').trim(), hunks: [] };
      files.push(current);
      return;
    }

    if (!current) {
      current = { label: '', hunks: [] };
      files.push(current);
    }

    if (line.startsWith('--- ') || line.startsWith('+++ ')) return;

    if (line.startsWith('@@')) {
      pushHunk();
      hunk = { header: line, lines: [] };
      return;
    }

    if (!hunk) return;

    if (line.startsWith('+')) hunk.lines.push({ type: 'add', text: line.slice(1) });
    else if (line.startsWith('-')) hunk.lines.push({ type: 'remove', text: line.slice(1) });
    else if (line.startsWith('\\')) hunk.lines.push({ type: 'meta', text: line });
    else hunk.lines.push({ type: 'context', text: line.replace(/^ /, '') });
  });

  pushHunk();
  return files.filter((file) => file.hunks.length > 0);
};

const countLines = (files, type) =>
  files.reduce(
    (total, file) =>
      total + file.hunks.reduce((n, h) => n + h.lines.filter((l) => l.type === type).length, 0),
    0
  );

function DiffView({ diff, changedDocuments = [] }) {
  const [wrap, setWrap] = useState(true);
  const files = useMemo(() => (diff ? parseDiff(diff) : []), [diff]);

  if (!diff || files.length === 0) {
    return (
      <div className="diff-empty">
        <p>
          No diff was recorded for this change. Diffs are generated from the run that
          detected the change onwards — sets last changed before this was in place show
          the full snapshot below instead.
        </p>
      </div>
    );
  }

  const added = countLines(files, 'add');
  const removed = countLines(files, 'remove');

  return (
    <div className="diff-view">
      <div className="diff-toolbar">
        <div className="diff-stats">
          <span className="diff-stat added">+{added}</span>
          <span className="diff-stat removed">−{removed}</span>
          <span className="diff-stat-label">
            {changedDocuments.length > 0
              ? `across ${changedDocuments.length} document${changedDocuments.length === 1 ? '' : 's'}`
              : 'lines changed'}
          </span>
        </div>
        <button
          type="button"
          className="diff-toggle"
          onClick={() => setWrap((value) => !value)}
          aria-pressed={wrap}
        >
          {wrap ? 'No wrap' : 'Wrap lines'}
        </button>
      </div>

      {files.map((file, fileIndex) => (
        <section className="diff-file" key={`${file.label}-${fileIndex}`}>
          {file.label && <h4 className="diff-file-label">{file.label}</h4>}
          {file.hunks.map((h, hunkIndex) => (
            <div className="diff-hunk" key={`${h.header}-${hunkIndex}`}>
              <div className="diff-hunk-header">{h.header}</div>
              <pre className={`diff-lines${wrap ? ' wrap' : ''}`}>
                {h.lines.map((line, lineIndex) => (
                  <span className={`diff-line ${line.type}`} key={lineIndex}>
                    <span className="diff-marker" aria-hidden="true">
                      {line.type === 'add' ? '+' : line.type === 'remove' ? '−' : ' '}
                    </span>
                    {line.text || ' '}
                  </span>
                ))}
              </pre>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

export default DiffView;
