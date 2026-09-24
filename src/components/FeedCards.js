import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatShortDay } from '../utils/constants';
import { blurbOf, isNew, RELEVANCE, TOPIC_LABELS } from '../utils/news';

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

function ExternalTitle({ item }) {
  return (
    <h3 className="feed-title">
      <a href={item.url} target="_blank" rel="noopener noreferrer">
        {item.title}
        <span className="external-mark" aria-hidden="true"> ↗</span>
        <span className="visually-hidden"> (opens in a new tab)</span>
      </a>
    </h3>
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

function Coverage({ entries }) {
  const [open, setOpen] = useState(false);
  if (!entries || entries.length === 0) return null;
  const names = [...new Set(entries.map((entry) => entry.publisher).filter(Boolean))];
  return (
    <div className="coverage">
      <button
        type="button"
        className="link-button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        Also reported by {names.slice(0, 3).join(', ')}
        {names.length > 3 ? ` and ${names.length - 3} more` : ''}
      </button>
      {open && (
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
      )}
    </div>
  );
}

export function NewsCard({ item, since, policyNames = {}, compact = false }) {
  const fresh = isNew(item, since);
  const blurb = blurbOf(item);
  const via = item.publisher && item.source_name !== item.publisher ? item.source_name : null;

  return (
    <article className={`feed-card${fresh ? ' is-new' : ''}${compact ? ' compact' : ''}`}>
      <div className="feed-meta">
        {fresh && <NewBadge />}
        <RelevanceBadge level={item.relevance} />
        <span className="feed-source">{item.publisher || item.source_name}</span>
        {compact && <span className="feed-date">{formatShortDay(item.published)}</span>}
        {!compact && via && <span className="feed-via">via {via}</span>}
      </div>
      <ExternalTitle item={item} />
      {blurb && <p className="feed-blurb">{blurb}</p>}
      {!compact && item.relevance_source === 'model' && item.relevance_reason && (
        <p className="feed-reason">{item.relevance_reason}</p>
      )}
      <RelatedPolicies ids={item.related_policies} policyNames={policyNames} />
      {!compact && item.topics?.length > 0 && (
        <ul className="topic-chips" aria-label="Topics">
          {item.topics.map((topic) => (
            <li key={topic}>{TOPIC_LABELS[topic] || topic}</li>
          ))}
        </ul>
      )}
      {!compact && <Coverage entries={item.coverage} />}
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
  return props.item.kind === 'incident' ? <IncidentCard {...props} /> : <NewsCard {...props} />;
}
