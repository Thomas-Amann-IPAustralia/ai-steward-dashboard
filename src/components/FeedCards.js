import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatDate, formatShortDay } from '../utils/constants';
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

/**
 * Cards for news items and AI incidents.
 *
 * Every card leads with the original's own headline linking to the original,
 * so nothing the model wrote stands between the reader and the source. The
 * model's TLDR, when there is one, sits under it as plain text; a card with
 * no TLDR shows the publisher's excerpt instead, and never an invented one.
 */

export function RelevanceBadge({ level }) {
  const meta = RELEVANCE[level];
  if (!meta) return null;
  return (
    <span className={`relevance-badge relevance-${level}`} title={meta.description}>
      {meta.label}
    </span>
  );
}

export function NewBadge() {
  return <span className="new-badge">New</span>;
}

function ExternalTitle({ item, as: Tag = 'h3', className = 'feed-title' }) {
  return (
    <Tag className={className}>
      <a href={item.url} target="_blank" rel="noopener noreferrer">
        {item.title}
        <span className="visually-hidden"> (opens in a new tab)</span>
      </a>
    </Tag>
  );
}

function RelatedPolicies({ ids, policyNames }) {
  const known = (ids || []).filter((id) => policyNames[id]);
  if (known.length === 0) return null;
  return (
    <p className="related-policies">
      <span className="related-label">Monitored policy:</span>{' '}
      {known.map((id, index) => (
        <React.Fragment key={id}>
          {index > 0 && ', '}
          <Link to={`/policy/${id}`}>{policyNames[id]}</Link>
        </React.Fragment>
      ))}
    </p>
  );
}

const MARK_PALETTE = ['#00529B', '#0f766e', '#7c3aed', '#b45309', '#be123c', '#15803d', '#0369a1', '#7e22ce'];

const markColor = (name) => {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) % 100000;
  return MARK_PALETTE[hash % MARK_PALETTE.length];
};

/** A coloured tile with the outlet's initials — recognisable without a
 *  third-party favicon request. */
export function OutletMark({ name }) {
  return (
    <span className="outlet-mark" style={{ backgroundColor: markColor(name || '?') }} aria-hidden="true">
      {outletInitials(name)}
    </span>
  );
}

/** "+4 outlets", opening a list of the other coverage. */
function CoverageToggle({ entries, open, onToggle }) {
  if (!entries || entries.length === 0) return null;
  return (
    <button type="button" className="meta-button" onClick={onToggle} aria-expanded={open}>
      +{entries.length} outlet{entries.length === 1 ? '' : 's'}
    </button>
  );
}

function CoverageList({ entries }) {
  return (
    <ul className="coverage-list">
      {entries.map((entry) => (
        <li key={entry.url}>
          <a href={entry.url} target="_blank" rel="noopener noreferrer">
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
 * One news item as a scannable row: a coloured edge for relevance, the
 * outlet's mark, the headline, one line of summary, and a single meta line.
 * Everything a reader needs to decide whether to click, in two seconds.
 */
export function NewsRow({ item, since, policyNames = {}, compact = false }) {
  const [open, setOpen] = useState(false);
  const fresh = isNew(item, since);
  const blurb = blurbOf(item);
  const outlet = publisherOf(item);
  const topics = compact ? [] : (item.topics || []).slice(0, 2);

  return (
    <article className={`news-row rel-${item.relevance || 1}${fresh ? ' is-new' : ''}${compact ? ' compact' : ''}`}>
      <OutletMark name={outlet} />
      <div className="news-row-main">
        <div className="news-row-head">
          <ExternalTitle item={item} className="news-row-title" />
          <time className="news-row-time" dateTime={item.published} title={formatDate(item.published)}>
            {formatAgo(item.published)}
          </time>
        </div>
        {blurb && <p className="news-row-blurb">{blurb}</p>}
        <div className="news-row-meta">
          {fresh && <NewBadge />}
          <span className="news-row-outlet">{outlet}</span>
          <RelevanceBadge level={item.relevance} />
          {item.paywalled && <span className="paywall-tag" title="This outlet may ask you to subscribe">Subscriber</span>}
          {topics.map((topic) => (
            <span key={topic} className="topic-tag">{TOPIC_LABELS[topic] || topic}</span>
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
export function TopStory({ item, since, policyNames = {} }) {
  const [open, setOpen] = useState(false);
  const fresh = isNew(item, since);
  const blurb = blurbOf(item);
  const outlet = publisherOf(item);

  return (
    <article className={`top-story rel-${item.relevance || 1}${fresh ? ' is-new' : ''}`}>
      <div className="top-story-meta">
        <OutletMark name={outlet} />
        <span className="news-row-outlet">{outlet}</span>
        <time dateTime={item.published} title={formatDate(item.published)}>{formatAgo(item.published)}</time>
      </div>
      <ExternalTitle item={item} className="top-story-title" />
      {blurb && <p className="top-story-blurb">{blurb}</p>}
      <div className="news-row-meta">
        {fresh && <NewBadge />}
        <RelevanceBadge level={item.relevance} />
        {item.paywalled && <span className="paywall-tag">Subscriber</span>}
        <RelatedLinks ids={item.related_policies} policyNames={policyNames} />
        <CoverageToggle entries={item.coverage} open={open} onToggle={() => setOpen((v) => !v)} />
      </div>
      {open && <CoverageList entries={item.coverage} />}
    </article>
  );
}

const HARM_CLASS = {
  'AI incident': 'harm-incident',
  'AI hazard': 'harm-hazard',
};

export function IncidentCard({ item, since, policyNames = {}, compact = false }) {
  const fresh = isNew(item, since);
  const incident = item.incident || {};
  const blurb = blurbOf(item);
  const tags = [...(incident.industries || []).slice(0, 2), ...(incident.harm_types || []).slice(0, 2)];

  return (
    <article className={`feed-card incident-card${fresh ? ' is-new' : ''}${compact ? ' compact' : ''}`}>
      <div className="feed-meta">
        {fresh && <NewBadge />}
        {incident.harm_level && (
          <span
            className={`harm-badge ${HARM_CLASS[incident.harm_level] || ''}`}
            title={
              incident.harm_level === 'AI hazard'
                ? 'An event that could plausibly have led to harm'
                : 'An event where an AI system led to actual harm'
            }
          >
            {incident.harm_level.replace('AI ', '')}
          </span>
        )}
        {incident.country && <span className="feed-source">{incident.country}</span>}
        <span className="feed-date">{formatShortDay(item.published)}</span>
        {incident.articles > 0 && (
          <span className="feed-reach" title="News articles the OECD has linked to this incident">
            {incident.articles.toLocaleString('en-AU')} report{incident.articles === 1 ? '' : 's'}
          </span>
        )}
      </div>
      <ExternalTitle item={item} />
      {blurb && <p className="feed-blurb">{blurb}</p>}
      <RelatedPolicies ids={item.related_policies} policyNames={policyNames} />
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
    </article>
  );
}

export function FeedCard(props) {
  return props.item.kind === 'incident' ? <IncidentCard {...props} /> : <NewsRow {...props} />;
}
