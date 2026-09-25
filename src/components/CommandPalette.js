import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatRelative, primaryUrl, timestampOf } from '../utils/constants';
import { publisherOf, rankItems } from '../utils/news';
import Icon from './Icon';
import Lettermark from './Lettermark';

const PAGES = [
  { label: 'Overview', to: '/', icon: 'overview', keywords: 'home briefing dashboard' },
  { label: 'Policy watch', to: '/policies', icon: 'policy', keywords: 'policies terms changes review' },
  { label: 'News', to: '/news', icon: 'news', keywords: 'stories feed' },
  { label: 'AI incidents', to: '/incidents', icon: 'incident', keywords: 'oecd harm hazard' },
  { label: 'Transparency statements', to: '/transparency', icon: 'eye', keywords: 'agencies register dta adoption' },
  { label: 'Sources', to: '/sources', icon: 'sources', keywords: 'feeds health status filtering' },
];

const GROUP_LIMITS = { Pages: 6, Policies: 8, Statements: 6, News: 6, Incidents: 4, Actions: 4 };

/** Every word of the query appears somewhere in the entry. */
const matches = (entry, words) => words.every((word) => entry.haystack.includes(word));

const rank = (entry, query) => {
  const label = entry.label.toLowerCase();
  if (label.startsWith(query)) return 0;
  if (label.includes(query)) return 1;
  return 2;
};

/**
 * Search everything the dashboard knows — pages, monitored policies,
 * agencies' transparency statements, news and incidents — and jump to it
 * from the keyboard. Opened with Ctrl/⌘+K or
 * "/". News and incidents open the original in a new tab, as everywhere else.
 */
function CommandPalette({ open, onClose, policySets, feed, statements = [], actions = [] }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const returnFocus = useRef(null);

  const entries = useMemo(() => {
    const policyEntries = [...policySets]
      .sort((a, b) => timestampOf(b.last_amended) - timestampOf(a.last_amended))
      .map((set) => ({
        group: 'Policies',
        label: set.setName,
        sub: set.last_amended ? `${set.category} · changed ${formatRelative(set.last_amended)}` : set.category,
        mark: set,
        to: `/policy/${set.file_id}`,
        keywords: `${set.category} ${primaryUrl(set)} ${(set.urls || []).map((u) => u.url).join(' ')}`,
      }));
    const items = rankItems(feed?.items || []);
    const itemEntries = items.map((item) => ({
      group: item.kind === 'incident' ? 'Incidents' : 'News',
      label: item.title,
      sub: item.kind === 'incident' ? item.incident?.country || 'OECD AI Incidents Monitor' : publisherOf(item),
      icon: item.kind === 'incident' ? 'incident' : 'news',
      href: item.url,
      keywords: `${item.tldr || ''} ${item.summary || ''}`,
    }));
    const statementEntries = statements.map((statement) => ({
      group: 'Statements',
      label: statement.agency,
      sub: statement.last_change
        ? `AI transparency statement · changed ${formatRelative(statement.last_change.timestamp)}`
        : 'AI transparency statement',
      icon: 'eye',
      to: `/transparency?q=${encodeURIComponent(statement.agency)}`,
      keywords: `${statement.portfolio} ${statement.url}`,
    }));
    const actionEntries = actions.map((action) => ({ group: 'Actions', ...action }));
    const pageEntries = PAGES.map((page) => ({ group: 'Pages', ...page }));
    return [...pageEntries, ...policyEntries, ...statementEntries, ...itemEntries, ...actionEntries].map((entry) => ({
      ...entry,
      haystack: `${entry.label} ${entry.sub || ''} ${entry.keywords || ''}`.toLowerCase(),
    }));
  }, [policySets, feed, statements, actions]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const words = q.split(/\s+/).filter(Boolean);
    const pool = q
      ? entries.filter((entry) => matches(entry, words))
      : entries.filter((entry) => !['News', 'Incidents', 'Statements'].includes(entry.group));
    const byGroup = {};
    pool.forEach((entry) => {
      (byGroup[entry.group] = byGroup[entry.group] || []).push(entry);
    });
    return Object.keys(GROUP_LIMITS)
      .filter((group) => byGroup[group])
      .map((group) => ({
        group,
        entries: (q ? [...byGroup[group]].sort((a, b) => rank(a, q) - rank(b, q)) : byGroup[group]).slice(
          0,
          q ? GROUP_LIMITS[group] : Math.min(GROUP_LIMITS[group], 4)
        ),
      }));
  }, [entries, query]);

  const flat = useMemo(() => groups.flatMap((g) => g.entries), [groups]);

  useEffect(() => {
    if (!open) return undefined;
    returnFocus.current = document.activeElement;
    setQuery('');
    setActive(0);
    const frame = requestAnimationFrame(() => inputRef.current?.focus());
    return () => {
      cancelAnimationFrame(frame);
      returnFocus.current?.focus?.();
    };
  }, [open]);

  useEffect(() => setActive(0), [query]);

  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest' });
  }, [active]);

  if (!open) return null;

  const choose = (entry) => {
    if (!entry) return;
    onClose();
    if (entry.to) navigate(entry.to);
    else if (entry.href) window.open(entry.href, '_blank', 'noopener,noreferrer');
    else entry.run?.();
  };

  const onKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => (flat.length ? (i + 1) % flat.length : 0));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => (flat.length ? (i - 1 + flat.length) % flat.length : 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(flat[active]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
    }
  };

  let position = -1;

  return (
    <div className="palette-overlay" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Search the dashboard"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="palette-input">
          <Icon name="search" size={18} />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search policies, news, incidents…"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-results"
            aria-activedescendant={flat[active] ? `palette-option-${active}` : undefined}
            aria-autocomplete="list"
          />
          <kbd>Esc</kbd>
        </div>
        <div className="palette-results" id="palette-results" role="listbox" ref={listRef}>
          {flat.length === 0 && <p className="palette-empty">Nothing matches “{query}”.</p>}
          {groups.map(({ group, entries: groupEntries }) => (
            <div key={group} className="palette-group" role="presentation">
              <div className="palette-group-label" role="presentation">{group}</div>
              {groupEntries.map((entry) => {
                position += 1;
                const index = position;
                return (
                  <div
                    key={`${group}-${entry.label}-${index}`}
                    id={`palette-option-${index}`}
                    role="option"
                    aria-selected={index === active}
                    className={`palette-option${index === active ? ' active' : ''}`}
                    onMouseMove={() => setActive(index)}
                    onClick={() => choose(entry)}
                  >
                    <span className="palette-option-icon">
                      {entry.mark ? (
                        <Lettermark url={primaryUrl(entry.mark)} name={entry.mark.setName} size={20} />
                      ) : (
                        <Icon name={entry.icon || 'arrow-right'} size={16} />
                      )}
                    </span>
                    <span className="palette-option-text">
                      <span className="palette-option-label">{entry.label}</span>
                      {entry.sub && <span className="palette-option-sub">{entry.sub}</span>}
                    </span>
                    {entry.href && <Icon name="external" size={14} className="palette-option-hint" />}
                    {index === active && !entry.href && <Icon name="enter" size={14} className="palette-option-hint" />}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <div className="palette-foot" aria-hidden="true">
          <span><kbd>↑</kbd><kbd>↓</kbd> to move</span>
          <span><kbd>↵</kbd> to open</span>
          <span><kbd>Esc</kbd> to close</span>
        </div>
      </div>
    </div>
  );
}

export default CommandPalette;
