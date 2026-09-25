import React, { useMemo, useState } from 'react';
import { pairChangedLines } from '../utils/wordDiff';
import Icon from './Icon';

/**
 * Renders the unified diff that produced an analysis.
 *
 * The detail page used to lead with a <pre> dump of the entire snapshot, which
 * is the least useful element on the page — nobody reads 97 kB of terms of
 * service looking for the sentence that moved. The diff is already collapsed
 * to changed hunks with a few lines of context, and within a changed line the
 * words that actually differ are marked, so the eye lands on the edit.
 */

export const parseDiff = (text) => {
  const files = [];
  let current = null;
  let hunk = null;

  const pushHunk = () => {
    if (hunk && current) current.hunks.push({ ...hunk, lines: pairChangedLines(hunk.lines) });
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

const countLines = (hunks, type) =>
  hunks.reduce((n, h) => n + h.lines.filter((l) => l.type === type).length, 0);

/** "@@ -12,4 +12,5 @@" → "Line 12". */
const hunkLabel = (header) => {
  const match = header.match(/\+(\d+)/);
  return match ? `Line ${match[1]}` : header;
};

function LineText({ line }) {
  if (!line.segments) return line.text || ' ';
  return line.segments.map((segment, index) =>
    segment.changed ? (
      <mark key={index} className={line.type === 'add' ? 'word-add' : 'word-remove'}>
        {segment.text}
      </mark>
    ) : (
      <React.Fragment key={index}>{segment.text}</React.Fragment>
    )
  );
}

function DiffView({ diff, changedDocuments = [] }) {
  const [wrap, setWrap] = useState(true);
  const files = useMemo(() => (diff ? parseDiff(diff) : []), [diff]);

  if (!diff || files.length === 0) {
    return (
      <div className="empty-state subtle">
        <span className="empty-icon"><Icon name="file" size={20} /></span>
        <div>
          <strong>No diff recorded for this change</strong>
          <p>
            Diffs are generated from the run that detected the change onwards — sets last changed before this was in
            place show the full captured text at the foot of the page instead.
          </p>
        </div>
      </div>
    );
  }

  const allHunks = files.flatMap((file) => file.hunks);
  const added = countLines(allHunks, 'add');
  const removed = countLines(allHunks, 'remove');
  const documentCount = changedDocuments.length || files.filter((file) => file.label).length;

  return (
    <div className="diff-view">
      <div className="diff-toolbar">
        <div className="diff-stats">
          <span className="diff-stat added">+{added}</span>
          <span className="diff-stat removed">−{removed}</span>
          <span className="diff-bar" aria-hidden="true">
            {Array.from({ length: 5 }, (_, i) => {
              const total = added + removed || 1;
              const green = Math.round((added / total) * 5);
              return <i key={i} className={i < green ? 'add' : 'remove'} />;
            })}
          </span>
          <span className="diff-stat-label">
            lines {documentCount > 0 ? `across ${documentCount} document${documentCount === 1 ? '' : 's'}` : 'changed'}
          </span>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setWrap((value) => !value)} aria-pressed={!wrap}>
          {wrap ? 'Don’t wrap lines' : 'Wrap lines'}
        </button>
      </div>

      {files.map((file, fileIndex) => (
        <details className="diff-file" key={`${file.label}-${fileIndex}`} open>
          <summary className="diff-file-head">
            <Icon name="chevron-right" size={14} className="disclosure-chevron" />
            <Icon name="file" size={14} />
            <span className="diff-file-label">{file.label || 'Document'}</span>
            <span className="diff-file-stats">
              <span className="added">+{countLines(file.hunks, 'add')}</span>
              <span className="removed">−{countLines(file.hunks, 'remove')}</span>
            </span>
          </summary>
          {file.hunks.map((h, hunkIndex) => (
            <div className="diff-hunk" key={`${h.header}-${hunkIndex}`}>
              <div className="diff-hunk-header" title={h.header}>{hunkLabel(h.header)}</div>
              <pre className={`diff-lines${wrap ? ' wrap' : ''}`}>
                {h.lines.map((line, lineIndex) => (
                  <span className={`diff-line ${line.type}`} key={lineIndex}>
                    <span className="diff-marker" aria-hidden="true">
                      {line.type === 'add' ? '+' : line.type === 'remove' ? '−' : ' '}
                    </span>
                    <span className="visually-hidden">{line.type === 'add' ? 'Added: ' : line.type === 'remove' ? 'Removed: ' : ''}</span>
                    <span className="diff-text">
                      <LineText line={line} />
                    </span>
                  </span>
                ))}
              </pre>
            </div>
          ))}
        </details>
      ))}
    </div>
  );
}

export default DiffView;
