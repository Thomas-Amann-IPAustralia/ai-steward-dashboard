import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatDate, formatShortDay, safeHref } from '../utils/constants';
import {
  blurbOf,
  formatAgo,
  isAggregated,
  isNew,
  outletInitials,
  publisherOf,
  RELEVANCE,
  TOPIC_LABELS,
} from '../utils/news';
import Icon from './Icon';
import { colorFor } from './Lettermark';

/**
 * Cards for news items and AI incidents.
 *
 * Every card leads with the original's own headline linking to the original,
 * so nothing the model wrote stands between the reader and the source. The
 * model's TLDR, when there is one, sits under it as plain text; a card with
 * no TLDR shows the publisher's excerpt instead, and never an invented one.
 *
 * News is for reading, not acting on: relevance is shown as a quiet signal
 * (three bars, explained on hover and in the key), never as a call to action.
 * The only things this dashboard asks anyone to act on are policy changes.
 */

export function RelevanceSignal({ level }) {
  const meta = RELEVANCE[level];
  if (!meta) return null;
  return (
    <span className={`signal signal-${level}`} title={`${meta.label}: ${meta.description}`}>
      <span className="signal-bars" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      <span className="visually-hidden">{meta.label}</span>
    </span>
  );
}

export function NewBadge() {
  return <span className="new-badge">New</span>;
}

function ExternalTitle({ item, as: Tag = 'h3', className = 'feed-title' }) {
  return (
    <Tag className={className}>
      <a href={safeHref(item.url)} target="_blank" rel="noopener noreferrer">
        {item.title}
        <span className="visually-hidden"> (opens in a new tab)</span>
      </a>
    </Tag>
  );
}

/** A tile with the outlet's initials — recognisable without a
 *  third-party favicon request. */
export function OutletMark({ name, size = 32 }) {
  const initials = outletInitials(name);
  return (
    <span
      className="outlet-mark"
      style={{
        '--mark': colorFor(name || '?'),
        width: size,
        height: size,
        fontSize: initials.length > 2 ? size * 0.3 : size * 0.38,
      }}
      aria-hidden="true"
    >
      {initials}
    </span>
  );
}

/** "+4 outlets", opening a list of the other coverage. */
function CoverageToggle({ entries, open, onToggle }) {
  if (!entries || entries.length === 0) return null;
  return (
    <button type="button" className="meta-button" onClick={onToggle} aria-expanded={open}>
      <Icon name="layers" size={13} />+{entries.length} outlet{entries.length === 1 ? '' : 's'}
    </button>
  );
}

function CoverageList({ entries }) {
  return (
    <ul className="coverage-list">
      {entries.map((entry) => (
        <li key={entry.url}>
          <a href={safeHref(entry.url)} target="_blank" rel="noopener noreferrer">
            {entry.title}
          </a>{' '}
          <span className="coverage-publisher">— {entry.publisher}</span>
        </li>
      ))}
    </ul>
  );
}

function RelatedLinks({ ids, policyNames }) {
  const known = (ids || []).filter((id) => policyNames[id]);
  return known.map((id) => (
    <Link key={id} to={`/policy/${id}`} className="policy-link" title="A policy this dashboard monitors">
      {policyNames[id]}
    </Link>
  ));
}

/**
 * One news item as a scannable row: the outlet's mark, the headline, one line
 * of summary, and a single meta line. Everything a reader needs to decide
 * whether to click, in two seconds.
 */
export function NewsRow({ item, since, policyNames = {}, compact = false }) {
  const [open, setOpen] = useState(false);
  const fresh = isNew(item, since);
  const blurb = blurbOf(item);
  const outlet = publisherOf(item);
  const topics = compact ? [] : (item.topics || []).slice(0, 2);

  return (
    <article className={`news-row rel-${item.relevance || 1}${fresh ? ' is-new' : ''}${compact ? ' compact' : ''}`}>
      <OutletMark name={outlet} size={compact ? 28 : 34} />
      <div className="news-row-main">
        <ExternalTitle item={item} className="news-row-title" />
        {blurb && <p className="news-row-blurb">{blurb}</p>}
        <div className="news-row-meta">
          {fresh && <NewBadge />}
          <span className="news-row-outlet">{outlet}</span>
          <time className="news-row-time" dateTime={item.published} title={formatDate(item.published)}>
            {formatAgo(item.published)}
          </time>
          <RelevanceSignal level={item.relevance} />
          {item.paywalled && <span className="tag" title="This outlet may ask you to subscribe">Subscriber</span>}
          {topics.map((topic) => (
            <span key={topic} className="tag">{TOPIC_LABELS[topic] || topic}</span>
          ))}
          <RelatedLinks ids={item.related_policies} policyNames={policyNames} />
          {!compact && <CoverageToggle entries={item.coverage} open={open} onToggle={() => setOpen((v) => !v)} />}
          {!compact && isAggregated(item) && <span className="via-tag">via Google News</span>}
        </div>
        {open && <CoverageList entries={item.coverage} />}
      </div>
    </article>
  );
}

/** A lead story: the same information as a row, with room to read. */
export function TopStory({ item, since, policyNames = {}, featured = false }) {
  const [open, setOpen] = useState(false);
  const fresh = isNew(item, since);
  const blurb = blurbOf(item);
  const outlet = publisherOf(item);

  return (
    <article className={`top-story${featured ? ' featured' : ''}${fresh ? ' is-new' : ''}`}>
      <div className="top-story-meta">
        <OutletMark name={outlet} size={24} />
        <span className="news-row-outlet">{outlet}</span>
        <time dateTime={item.published} title={formatDate(item.published)}>{formatAgo(item.published)}</time>
        {fresh && <NewBadge />}
      </div>
      <ExternalTitle item={item} className="top-story-title" />
      {blurb && <p className="top-story-blurb">{blurb}</p>}
      <div className="news-row-meta">
        <RelevanceSignal level={item.relevance} />
        {item.paywalled && <span className="tag">Subscriber</span>}
        <RelatedLinks ids={item.related_policies} policyNames={policyNames} />
        <CoverageToggle entries={item.coverage} open={open} onToggle={() => setOpen((v) => !v)} />
      </div>
      {open && <CoverageList entries={item.coverage} />}
    </article>
  );
}

const HARM = {
  'AI incident': { className: 'harm-incident', label: 'Incident', title: 'An event where an AI system led to actual harm' },
  'AI hazard': { className: 'harm-hazard', label: 'Hazard', title: 'An event that could plausibly have led to harm' },
};

export function HarmBadge({ level }) {
  const meta = HARM[level];
  if (!level) return null;
  return (
    <span className={`harm-badge ${meta?.className || ''}`} title={meta?.title}>
      {meta?.label || level}
    </span>
  );
}

export function IncidentCard({ item, since, policyNames = {}, compact = false }) {
  const fresh = isNew(item, since);
  const incident = item.incident || {};
  const blurb = blurbOf(item);
  const tags = [...(incident.industries || []).slice(0, 2), ...(incident.harm_types || []).slice(0, 2)];
  const known = (item.related_policies || []).filter((id) => policyNames[id]);

  return (
    <article className={`incident-card${fresh ? ' is-new' : ''}${compact ? ' compact' : ''}`}>
      <span className={`incident-icon ${HARM[incident.harm_level]?.className || ''}`} aria-hidden="true">
        <Icon name="incident" size={compact ? 15 : 17} />
      </span>
      <div className="incident-main">
        <div className="feed-meta">
          {fresh && <NewBadge />}
          <HarmBadge level={incident.harm_level} />
          {incident.country && (
            <span className="feed-source">
              <Icon name="globe" size={13} />
              {incident.country}
            </span>
          )}
          <span className="feed-date">{formatShortDay(item.published)}</span>
          {incident.articles > 0 && (
            <span className="feed-reach" title="News articles the OECD has linked to this incident">
              {incident.articles.toLocaleString('en-AU')} report{incident.articles === 1 ? '' : 's'}
            </span>
          )}
        </div>
        <ExternalTitle item={item} />
        {blurb && <p className="feed-blurb">{blurb}</p>}
        {known.length > 0 && (
          <p className="related-policies">
            <span className="related-label">Monitored policy</span>
            <RelatedLinks ids={known} policyNames={policyNames} />
          </p>
        )}
        {!compact && tags.length > 0 && (
          <ul className="topic-chips" aria-label="Sector and harm">
            {tags.map((tag) => (
              <li key={tag}>{tag}</li>
            ))}
          </ul>
        )}
        {!compact && incident.aiid_ids?.length > 0 && (
          <p className="feed-reason">
            Also in the AI Incident Database:{' '}
            {incident.aiid_ids.map((id, index) => (
              <React.Fragment key={id}>
                {index > 0 && ', '}
                <a href={`https://incidentdatabase.ai/cite/${id}/`} target="_blank" rel="noopener noreferrer">
                  #{id}
                </a>
              </React.Fragment>
            ))}
          </p>
        )}
      </div>
    </article>
  );
}

export function FeedCard(props) {
  return props.item.kind === 'incident' ? <IncidentCard {...props} /> : <NewsRow {...props} />;
}
