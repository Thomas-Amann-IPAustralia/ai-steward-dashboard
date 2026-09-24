import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  changeSummaryOf,
  formatDate,
  formatRelative,
  primaryUrl,
  revertedAfterChange,
  timestampOf,
} from '../utils/constants';
import { buildBriefing, copyToClipboard } from '../utils/briefing';
import { isAustralianIncident, isNew, rankItems, withinDays } from '../utils/news';
import { FeedCard, NewBadge } from './FeedCards';
import Lettermark from './Lettermark';
import PriorityBadge from './PriorityBadge';
import { HealthPill } from './SourceHealth';

const DAY_MS = 24 * 60 * 60 * 1000;
const RECENT_DAYS = 30;
const BRIEFING_DAYS = 7;
const ATTENTION_PRIORITIES = new Set(['critical', 'high']);

/** What a failing source means for the reader, as specifically as health.json allows. */
const failingMessage = (source) => {
  const { documents_failing: failing, documents_total: total } = source;
  const partial = failing && total && failing < total;
  const which = partial
    ? `${failing} of its ${total} documents ${failing === 1 ? 'is' : 'are'} not being read`
    : 'It is not being read';
  if (source.status !== 'failing') {
    return `The last read of ${partial ? `${failing} of its ${total} documents` : 'this source'} failed; the stored copy was kept.`;
  }
  const since = source.last_success
    ? ` The last complete read was ${formatRelative(source.last_success)}.`
    : '';
  return `${which}, so “no changes” there means “not checked”.${since}`;
};

/**
 * The overview: one page that answers "what do I need to know?".
 *
 * It used to cover policy changes from the last seven days only, so a
 * steward checking in fortnightly never saw Anthropic's critical change on
 * 13 September at all. Now: what is new since this browser last visited,
 * anything that needs attention, a month of policy changes, and the news and
 * incidents worth reading — each linking through to its full view.
 */
function DashboardHome({ policySets, health, feed, since }) {
  const [copied, setCopied] = useState(null);

  const brief = useMemo(() => {
    const now = Date.now();
    const healthSources = health?.sources || {};
    const withHealth = policySets.map((set) => ({
      ...set,
      health: healthSources[set.setName] || { status: set.status || 'ok' },
    }));

    const failingSources = withHealth
      .filter((set) => set.health.status && set.health.status !== 'ok')
      .map((set) => ({
        setName: set.setName,
        file_id: set.file_id,
        status: set.health.status,
        last_success: set.health.last_success || set.last_success,
        documents_failing: set.health.documents_failing,
        documents_total: set.health.documents_total,
      }))
      .sort((a, b) => (a.status === 'failing' ? 0 : 1) - (b.status === 'failing' ? 0 : 1));

    const changedWithin = (days) =>
      withHealth
        .filter((set) => timestampOf(set.last_amended) > now - days * DAY_MS && set.last_verdict !== 'no_material_change')
        .sort((a, b) => timestampOf(b.last_amended) - timestampOf(a.last_amended));

    const recentChanges = changedWithin(RECENT_DAYS);
    const attention = recentChanges.filter((set) =>
      ATTENTION_PRIORITIES.has((set.last_priority || '').toLowerCase())
    );
    const recentIds = new Set(recentChanges.map((set) => set.file_id));
    const stable = withHealth.filter((set) => !recentIds.has(set.file_id) && set.health.status === 'ok');

    const items = feed?.items || [];
    const news = items.filter((item) => item.kind === 'news');
    const topNews = rankItems(withinDays(news, BRIEFING_DAYS).filter((item) => item.relevance >= 2)).slice(0, 6);
    const localIncidents = rankItems(withinDays(items.filter(isAustralianIncident), RECENT_DAYS)).slice(0, 4);

    const lastScan = withHealth.reduce((latest, set) => Math.max(latest, timestampOf(set.last_checked)), 0);

    const weekChanges = changedWithin(BRIEFING_DAYS);
    const weekIds = new Set(weekChanges.map((set) => set.file_id));

    return {
      failingSources,
      recentChanges,
      attention,
      stable,
      topNews,
      localIncidents,
      lastScan,
      weekChanges,
      weekStable: withHealth.filter((set) => !weekIds.has(set.file_id) && set.health.status === 'ok').length,
      newChanges: since ? recentChanges.filter((set) => timestampOf(set.last_amended) > since).length : 0,
      newNews: news.filter((item) => item.relevance >= 2 && isNew(item, since)).length,
      newIncidents: items.filter((item) => isAustralianIncident(item) && isNew(item, since)).length,
      weekIncidents: withinDays(items.filter(isAustralianIncident), BRIEFING_DAYS),
      weekNews: rankItems(withinDays(news, BRIEFING_DAYS).filter((item) => item.relevance >= 3)).slice(0, 8),
    };
  }, [policySets, health, feed, since]);

  const policyNames = useMemo(
    () => Object.fromEntries(policySets.map((set) => [set.file_id, set.setName])),
    [policySets]
  );

  const copyBriefing = async () => {
    const ok = await copyToClipboard(
      buildBriefing({
        recentChanges: brief.weekChanges,
        failingSources: brief.failingSources,
        stableCount: brief.weekStable,
        topNews: brief.weekNews,
        incidents: brief.weekIncidents,
      })
    );
    setCopied(ok ? 'Copied to clipboard' : 'Could not copy — select and copy manually');
    setTimeout(() => setCopied(null), 4000);
  };

  const changeRow = (set) => {
    const summary = changeSummaryOf(set);
    const fresh = since && timestampOf(set.last_amended) > since;
    return (
      <li key={set.file_id} className={`briefing-item${fresh ? ' is-new' : ''}`}>
        <div className="briefing-item-head">
          <Lettermark url={primaryUrl(set)} name={set.setName} />
          <Link className="briefing-item-name" to={`/policy/${set.file_id}`}>
            {set.setName}
          </Link>
          {fresh && <NewBadge />}
          <PriorityBadge priority={set.last_priority} date={set.last_amended} solid />
          <HealthPill status={set.health?.status} />
        </div>
        {summary && <p className="briefing-item-summary">{summary}</p>}
        {revertedAfterChange(set) && (
          <p className="revert-note">
            Since returned to an earlier version ({formatRelative(revertedAfterChange(set))}) — this
            change may have been undone.
          </p>
        )}
        <div className="briefing-item-meta">
          {set.last_change?.changed_documents?.length > 0 && (
            <span className="changed-documents">{set.last_change.changed_documents.join(', ')}</span>
          )}
          <span>Changed {formatRelative(set.last_amended)}</span>
        </div>
      </li>
    );
  };

  const hasNewSinceVisit = brief.newChanges + brief.newNews + brief.newIncidents > 0;

  return (
    <div className="dashboard-home">
      <div className="briefing-header">
        <div>
          <h2>Your AI briefing</h2>
          <p className="briefing-subtitle">
            {brief.lastScan
              ? `Policies checked ${formatDate(new Date(brief.lastScan).toISOString())}`
              : 'No completed policy scan recorded yet'}
            {feed?.generated_at && ` · news updated ${formatRelative(feed.generated_at)}`}
          </p>
        </div>
        <div className="briefing-actions">
          <button type="button" className="secondary-button" onClick={copyBriefing}>
            Copy weekly briefing
          </button>
          <span className="copy-feedback" role="status" aria-live="polite">
            {copied}
          </span>
        </div>
      </div>

      {since ? (
        <div className={`since-strip${hasNewSinceVisit ? '' : ' quiet'}`}>
          <span className="since-label">Since your last visit {formatRelative(new Date(since).toISOString())}:</span>
          {hasNewSinceVisit ? (
            <>
              <Link to="/policies">
                <strong>{brief.newChanges}</strong> policy change{brief.newChanges === 1 ? '' : 's'}
              </Link>
              <Link to="/news">
                <strong>{brief.newNews}</strong> relevant news item{brief.newNews === 1 ? '' : 's'}
              </Link>
              <Link to="/incidents">
                <strong>{brief.newIncidents}</strong> Australian AI incident{brief.newIncidents === 1 ? '' : 's'}
              </Link>
            </>
          ) : (
            <span>nothing new.</span>
          )}
        </div>
      ) : (
        <div className="since-strip welcome">
          This page brings together changes to the AI policies and terms APS staff rely on, the
          news around them, and AI incidents — checked every day. Items that arrive after this
          visit will be marked <NewBadge /> next time.
        </div>
      )}

      {(brief.attention.length > 0 || brief.failingSources.length > 0) && (
        <section className="briefing-section attention">
          <h3>Needs attention</h3>
          {brief.attention.length > 0 && <ul className="briefing-list">{brief.attention.map(changeRow)}</ul>}
          {brief.failingSources.length > 0 && (
            <ul className="briefing-list compact-list">
              {brief.failingSources.map((source) => (
                <li key={source.file_id || source.setName} className="briefing-item failing">
                  <div className="briefing-item-head">
                    <Link className="briefing-item-name" to={`/policy/${source.file_id}`}>
                      {source.setName}
                    </Link>
                    <HealthPill status={source.status} />
                  </div>
                  <p className="briefing-item-summary">{failingMessage(source)}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <div className="overview-grid">
        <div className="overview-column">
          <section className="briefing-section">
            <div className="section-head">
              <h3>Policy changes — last {RECENT_DAYS} days</h3>
              <Link to="/policies" className="section-link">All policies →</Link>
            </div>
            {brief.recentChanges.length === 0 ? (
              <p className="briefing-quiet">No material policy changes in the last {RECENT_DAYS} days.</p>
            ) : (
              <ul className="briefing-list">
                {brief.recentChanges
                  .filter((set) => !brief.attention.includes(set))
                  .map(changeRow)}
                {brief.recentChanges.every((set) => brief.attention.includes(set)) && (
                  <li className="briefing-quiet">Every recent change is listed under “Needs attention”.</li>
                )}
              </ul>
            )}
          </section>

          <section className="briefing-section stable">
            <h3>Checked and unchanged</h3>
            <p className="briefing-quiet">
              {brief.stable.length} of {policySets.length} monitored policy sets were checked and have
              not changed materially in {RECENT_DAYS} days.
            </p>
            <ul className="stable-chips">
              {brief.stable.map((set) => (
                <li key={set.file_id}>
                  <Link className="stable-chip" to={`/policy/${set.file_id}`}>
                    <Lettermark url={primaryUrl(set)} name={set.setName} size={14} />
                    <span>{set.setName}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <div className="overview-column">
          <section className="briefing-section">
            <div className="section-head">
              <h3>Top news this week</h3>
              <Link to="/news" className="section-link">All news →</Link>
            </div>
            {brief.topNews.length === 0 ? (
              <p className="briefing-quiet">
                {feed?.items?.length ? 'No highly relevant news in the last seven days.' : 'The news feed has not run yet.'}
              </p>
            ) : (
              <div className="feed-list">
                {brief.topNews.map((item) => (
                  <FeedCard key={item.id} item={item} since={since} policyNames={policyNames} compact />
                ))}
              </div>
            )}
          </section>

          <section className="briefing-section">
            <div className="section-head">
              <h3>AI incidents in Australia</h3>
              <Link to="/incidents" className="section-link">All incidents →</Link>
            </div>
            {brief.localIncidents.length === 0 ? (
              <p className="briefing-quiet">No AI incidents recorded in Australia in the last {RECENT_DAYS} days.</p>
            ) : (
              <div className="feed-list">
                {brief.localIncidents.map((item) => (
                  <FeedCard key={item.id} item={item} since={since} policyNames={policyNames} compact />
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

export default DashboardHome;
