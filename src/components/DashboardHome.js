import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useHistoryIndex } from '../hooks/useHistory';
import { useLatestAnalyses } from '../hooks/useLatestAnalyses';
import { useReviews } from '../hooks/useReviews';
import { useToast } from '../hooks/useToast';
import {
  changeSummaryOf,
  formatDate,
  formatRelative,
  formatShortDay,
  isAdoption,
  primaryUrl,
  PRIORITY_ORDER,
  revertedAfterChange,
  timestampOf,
} from '../utils/constants';
import { buildBriefing, copyToClipboard } from '../utils/briefing';
import { isAustralianIncident, isNew, rankItems, withinDays } from '../utils/news';
import { reviewQueue, REVIEW_WINDOW_DAYS } from '../utils/reviews';
import { dailySeries, dayTime, weeklySeries } from '../utils/series';
import ChangeTimeline from './ChangeTimeline';
import { Meter, StackedColumns } from './charts';
import { FeedCard, NewBadge } from './FeedCards';
import Icon from './Icon';
import Lettermark from './Lettermark';
import PriorityBadge from './PriorityBadge';
import { HealthPill } from './SourceHealth';

const DAY_MS = 24 * 60 * 60 * 1000;
const RECENT_DAYS = 30;
const BRIEFING_DAYS = 7;

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString('en-AU')} ${n === 1 ? one : many}`;

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
  const since = source.last_success ? ` Last complete read ${formatRelative(source.last_success)}.` : '';
  return `${which}, so “no changes” there means “not checked”.${since}`;
};

const sydneyNow = (options) => new Date().toLocaleString('en-AU', { timeZone: 'Australia/Sydney', ...options });

const greeting = () => {
  const hour = Number(sydneyNow({ hour: 'numeric', hourCycle: 'h23' }));
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
};

const sinceText = (since) => {
  const relative = formatRelative(new Date(since).toISOString());
  if (relative === 'today') return 'Since your visit earlier today';
  if (relative === 'yesterday') return 'Since your visit yesterday';
  return `Since your last visit ${relative}`;
};

const scrollToReview = () => document.getElementById('review-queue')?.scrollIntoView({ behavior: 'smooth', block: 'start' });

/** The day's briefing in two sentences, each figure linking to where it comes from. */
function Narrative({ brief, since }) {
  const { pending, done, failingSources } = brief;
  const latest = pending[0];
  const news = since ? brief.newNews : brief.weekRelevantNews;
  const incidents = since ? brief.newIncidents : brief.weekIncidents.length;

  return (
    <div className="narrative">
      <span className="narrative-icon" aria-hidden="true">
        <Icon name="sparkle" size={18} />
      </span>
      <p>
        {pending.length > 0 ? (
          <>
            <button type="button" className="inline-link strong" onClick={scrollToReview}>
              {plural(pending.length, 'policy change')}
            </button>{' '}
            {pending.length === 1 ? 'is' : 'are'} waiting for your review
            {latest && (
              <>
                {pending.length > 1 ? ', most recently ' : ': '}
                <Link to={`/policy/${latest.file_id}`}>{latest.setName}</Link>
                {latest.last_priority && ` (${latest.last_priority.toLowerCase()} priority)`}
              </>
            )}
            .{' '}
          </>
        ) : (
          <>
            <strong>You’re up to date on policy changes</strong>
            {done.length > 0
              ? ` — all ${plural(done.length, 'change')} from the last ${REVIEW_WINDOW_DAYS} days ${done.length === 1 ? 'has' : 'have'} been reviewed. `
              : ` — nothing material has changed in the last ${REVIEW_WINDOW_DAYS} days. `}
          </>
        )}
        {since ? sinceText(since) : 'In the last 7 days'},{' '}
        <Link to="/news">{plural(news, 'relevant story', 'relevant stories')}</Link> and{' '}
        <Link to="/incidents">{plural(incidents, 'Australian AI incident')}</Link>{' '}
        {since ? 'arrived' : 'were recorded'}.
        {failingSources.length > 0 && (
          <>
            {' '}
            <Link to="/sources" className="narrative-warning">
              {plural(failingSources.length, 'source')} {failingSources.length === 1 ? 'isn’t' : 'aren’t'} being read cleanly
            </Link>
            .
          </>
        )}
      </p>
    </div>
  );
}

function Kpi({ to, icon, label, value, sub, tone = '', children }) {
  return (
    <Link to={to} className={`kpi${tone ? ` tone-${tone}` : ''}`}>
      <span className="kpi-label">
        <Icon name={icon} size={15} />
        {label}
      </span>
      <span className="kpi-value">{value}</span>
      {children && <span className="kpi-chart">{children}</span>}
      {sub && <span className="kpi-sub">{sub}</span>}
    </Link>
  );
}

function ReviewItem({ set, summary, since, onToggle, done = false }) {
  const fresh = since && timestampOf(set.last_amended) > since;
  const reverted = revertedAfterChange(set);
  const documents = set.last_change?.changed_documents || [];

  return (
    <li className={`review-item${done ? ' done' : ''} p-${(set.last_priority || 'none').toLowerCase()}`}>
      <Lettermark url={primaryUrl(set)} name={set.setName} size={36} />
      <div className="review-main">
        <div className="review-head">
          <Link className="review-name" to={`/policy/${set.file_id}`}>{set.setName}</Link>
          {fresh && !done && <NewBadge />}
          <PriorityBadge priority={set.last_priority} solid />
          <HealthPill status={set.health?.status} />
        </div>
        {summary && !done && <p className="review-summary">{summary}</p>}
        {reverted && !done && (
          <p className="revert-note">
            <Icon name="undo" size={14} /> Since returned to an earlier version ({formatRelative(reverted)}) — this
            change may have been undone.
          </p>
        )}
        <div className="review-meta">
          <span><Icon name="clock" size={13} /> Changed {formatRelative(set.last_amended)}</span>
          {documents.length > 0 && (
            <span><Icon name="file" size={13} /> {documents.join(', ')}</span>
          )}
        </div>
      </div>
      <div className="review-actions">
        {!done && (
          <Link className="btn btn-secondary btn-sm" to={`/policy/${set.file_id}`}>
            See what changed
          </Link>
        )}
        <button
          type="button"
          className={`btn btn-sm ${done ? 'btn-ghost' : 'btn-primary'}`}
          onClick={() => onToggle(set, !done)}
        >
          <Icon name={done ? 'undo' : 'check'} size={15} />
          {done ? 'Undo' : 'Mark reviewed'}
        </button>
      </div>
    </li>
  );
}

/** A register of what other agencies have published: read for awareness, never reviewed. */
function AdoptionItem({ set, summary, since }) {
  const fresh = since && timestampOf(set.last_amended) > since;
  return (
    <li className="review-item">
      <Lettermark url={primaryUrl(set)} name={set.setName} size={36} />
      <div className="review-main">
        <div className="review-head">
          <Link className="review-name" to={`/policy/${set.file_id}`}>{set.setName}</Link>
          {fresh && <NewBadge />}
          <PriorityBadge priority={set.last_priority} date={set.last_amended} kind={set.kind} />
          <HealthPill status={set.health?.status} />
        </div>
        <p className="review-summary">
          {summary || (set.last_amended ? 'No summary recorded for the last update.' : 'No update recorded yet.')}
        </p>
        <div className="review-meta">
          <span>
            <Icon name="clock" size={13} />{' '}
            {set.last_amended ? `Updated ${formatRelative(set.last_amended)}` : `Checked ${formatRelative(set.last_checked)}`}
          </span>
        </div>
      </div>
    </li>
  );
}

/**
 * The overview: one page that answers "what do I need to know?".
 *
 * A steward acts on one thing here — a material change to a monitored
 * policy — so those lead as a review queue that empties as they are read.
 * News, incidents and what other agencies are doing are for awareness and
 * follow it. The briefing sentence
 * says the same in words, and the tiles and the activity chart show the shape
 * of it at a glance.
 */
function DashboardHome({ policySets, health, feed, since, loading }) {
  const { reviewed, markReviewed } = useReviews();
  const toast = useToast();
  const history = useHistoryIndex();
  const analyses = useLatestAnalyses(policySets.map((set) => set.file_id));

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

    // Adoption registers count as changed (they are not "unchanged"), but they
    // are reported on their own rather than as policy changes.
    const recentIds = new Set(changedWithin(RECENT_DAYS).map((set) => set.file_id));
    const stable = withHealth.filter((set) => !recentIds.has(set.file_id) && set.health.status === 'ok');
    const { pending, done } = reviewQueue(withHealth, reviewed, { now });

    const items = feed?.items || [];
    const news = items.filter((item) => item.kind === 'news');
    const relevantNews = news.filter((item) => item.relevance >= 2);
    const auIncidents = items.filter(isAustralianIncident);
    const weekAll = changedWithin(BRIEFING_DAYS);
    const weekChanges = weekAll.filter((set) => !isAdoption(set));
    const weekIds = new Set(weekAll.map((set) => set.file_id));

    return {
      failingSources,
      pending,
      done,
      stable,
      healthCounts: {
        ok: withHealth.filter((set) => set.health.status === 'ok').length,
        degraded: withHealth.filter((set) => set.health.status === 'degraded').length,
        failing: withHealth.filter((set) => set.health.status === 'failing').length,
      },
      topNews: rankItems(withinDays(relevantNews, BRIEFING_DAYS)).slice(0, 5),
      localIncidents: rankItems(withinDays(auIncidents, RECENT_DAYS)).slice(0, 4),
      lastScan: withHealth.reduce((latest, set) => Math.max(latest, timestampOf(set.last_checked)), 0),
      weekChanges,
      weekAdoption: weekAll.filter(isAdoption),
      adoption: withHealth
        .filter(isAdoption)
        .sort((a, b) => timestampOf(b.last_amended) - timestampOf(a.last_amended)),
      weekStable: withHealth.filter((set) => !weekIds.has(set.file_id) && set.health.status === 'ok').length,
      newNews: relevantNews.filter((item) => isNew(item, since)).length,
      newIncidents: auIncidents.filter((item) => isNew(item, since)).length,
      weekRelevantNews: withinDays(relevantNews, BRIEFING_DAYS).length,
      weekIncidents: withinDays(auIncidents, BRIEFING_DAYS),
      monthIncidents: withinDays(auIncidents, RECENT_DAYS).length,
      weekNews: rankItems(withinDays(news, BRIEFING_DAYS).filter((item) => item.relevance >= 3)).slice(0, 8),
      newsSeries: dailySeries(relevantNews, { days: 14, now, seriesOf: (item) => item.relevance }),
      incidentSeries: weeklySeries(auIncidents, { weeks: 8, now, seriesOf: () => 'incident' }),
    };
  }, [policySets, health, feed, since, reviewed]);

  const policyNames = useMemo(
    () => Object.fromEntries(policySets.map((set) => [set.file_id, set.setName])),
    [policySets]
  );

  const summaryOf = (set) => changeSummaryOf(set, analyses[set.file_id]);

  const copyBriefing = async () => {
    const ok = await copyToClipboard(
      buildBriefing({
        recentChanges: brief.weekChanges.map((set) => ({
          ...set,
          last_change: { ...set.last_change, summary: summaryOf(set) },
        })),
        failingSources: brief.failingSources,
        adoptionUpdates: brief.weekAdoption.map((set) => ({
          ...set,
          last_change: { ...set.last_change, summary: summaryOf(set) },
        })),
        stableCount: brief.weekStable,
        topNews: brief.weekNews,
        incidents: brief.weekIncidents,
      })
    );
    toast(ok ? 'Weekly briefing copied — paste it into an email or Teams' : 'Could not copy — your browser blocked the clipboard', {
      tone: ok ? 'default' : 'error',
    });
  };

  const toggleReviewed = (set, done) => {
    markReviewed(set, done);
    if (done) {
      toast(`Marked “${set.setName}” as reviewed`, { action: 'Undo', onAction: () => markReviewed(set, false) });
    }
  };

  const { healthCounts } = brief;
  const totalSources = policySets.length;

  if (loading && policySets.length === 0) {
    return (
      <div className="page">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-hero" />
        <div className="kpi-grid">
          {[0, 1, 2, 3].map((i) => <div className="skeleton skeleton-kpi" key={i} />)}
        </div>
      </div>
    );
  }

  return (
    <div className="page overview">
      <header className="page-head">
        <div>
          <p className="eyebrow">{sydneyNow({ weekday: 'long', day: 'numeric', month: 'long' })}</p>
          <h1>{greeting()}</h1>
          <p className="page-sub">
            {brief.lastScan
              ? `Policies checked ${formatDate(new Date(brief.lastScan).toISOString())}`
              : 'No completed policy scan recorded yet'}
            {feed?.generated_at && ` · news updated ${formatRelative(feed.generated_at)}`}
          </p>
        </div>
        <div className="page-actions">
          <button type="button" className="btn btn-secondary" onClick={copyBriefing}>
            <Icon name="copy" size={16} />
            Copy weekly briefing
          </button>
        </div>
      </header>

      {since ? (
        <Narrative brief={brief} since={since} />
      ) : (
        <>
          <div className="welcome-card">
            <strong>Welcome.</strong> This dashboard watches the AI policies and terms APS staff rely on,
            the news around them, and AI incidents — checked every day. Policy changes land in your review
            queue; everything else is here to read. Items that arrive after this visit will be marked{' '}
            <NewBadge /> next time.
          </div>
          <Narrative brief={brief} since={null} />
        </>
      )}

      <section className="kpi-grid" aria-label="At a glance">
        <Kpi
          to="/policies"
          icon="inbox"
          label="To review"
          value={brief.pending.length}
          tone={brief.pending.length ? 'action' : 'good'}
          sub={
            brief.pending.length
              ? `Latest: ${brief.pending[0].setName}`
              : `All caught up · ${plural(brief.done.length, 'change')} reviewed`
          }
        >
          {brief.pending.length > 0 && (
            <span className="kpi-breakdown">
              {PRIORITY_ORDER.map((level) => {
                const n = brief.pending.filter((set) => (set.last_priority || '').toLowerCase() === level).length;
                return n ? (
                  <span key={level} className={`p-${level}`}>
                    <span className="priority-dot" aria-hidden="true" />
                    {n} {level}
                  </span>
                ) : null;
              })}
            </span>
          )}
        </Kpi>
        <Kpi
          to="/sources"
          icon="sources"
          label="Sources reading"
          value={
            <>
              {healthCounts.ok}
              <span className="kpi-of">/{totalSources}</span>
            </>
          }
          tone={healthCounts.failing ? 'critical' : healthCounts.degraded ? 'warning' : ''}
          sub={
            healthCounts.failing || healthCounts.degraded
              ? [
                  healthCounts.failing && `${healthCounts.failing} not being read`,
                  healthCounts.degraded && `${healthCounts.degraded} failed last read`,
                ]
                  .filter(Boolean)
                  .join(' · ')
              : 'Every source read on the last run'
          }
        >
          <Meter
            ariaLabel={`${healthCounts.ok} reading, ${healthCounts.degraded} with a failed read, ${healthCounts.failing} not being read`}
            parts={[
              { label: 'reading normally', value: healthCounts.ok, swatch: 'status-good' },
              { label: 'last read failed', value: healthCounts.degraded, swatch: 'status-warning' },
              { label: 'not being read', value: healthCounts.failing, swatch: 'status-critical' },
            ]}
          />
        </Kpi>
        <Kpi to="/news" icon="news" label="Relevant news · 7 days" value={brief.weekRelevantNews} sub="Daily, last 14 days">
          <StackedColumns
            compact
            height={34}
            rows={brief.newsSeries}
            series={[
              { key: 2, label: 'Relevant', swatch: 'rel-2' },
              { key: 3, label: 'Highly relevant', swatch: 'rel-3' },
            ]}
            titleOf={(row) => formatShortDay(new Date(dayTime(row.key)).toISOString())}
            ariaLabel="Relevant stories per day over the last 14 days"
          />
        </Kpi>
        <Kpi
          to="/incidents"
          icon="incident"
          label="AU incidents · 30 days"
          value={brief.monthIncidents}
          sub="Weekly, last 8 weeks"
        >
          <StackedColumns
            compact
            height={34}
            rows={brief.incidentSeries}
            series={[{ key: 'incident', label: 'Australian AI incidents and hazards', swatch: 'viz-2' }]}
            titleOf={(row) => `Week of ${formatShortDay(new Date(dayTime(row.key)).toISOString())}`}
            ariaLabel="Australian AI incidents and hazards per week over the last 8 weeks"
          />
        </Kpi>
      </section>

      <div className="overview-grid">
        <div className="overview-col">
          <section className="card" id="review-queue" aria-labelledby="review-title">
            <div className="card-head">
              <div>
                <h2 id="review-title">
                  Policy changes to review
                  {brief.pending.length > 0 && <span className="count-pill action">{brief.pending.length}</span>}
                </h2>
                <p className="card-sub">
                  Material changes from the last {REVIEW_WINDOW_DAYS} days. Mark each one reviewed once you’ve read it —
                  this is remembered in this browser.
                </p>
              </div>
            </div>
            {brief.pending.length === 0 ? (
              <div className="empty-state">
                <span className="empty-icon good"><Icon name="check-circle" size={22} /></span>
                <div>
                  <strong>All caught up</strong>
                  <p>No policy changes are waiting for review. New ones will appear here after the daily check.</p>
                </div>
              </div>
            ) : (
              <ul className="review-list">
                {brief.pending.map((set) => (
                  <ReviewItem key={set.file_id} set={set} summary={summaryOf(set)} since={since} onToggle={toggleReviewed} />
                ))}
              </ul>
            )}
            {brief.done.length > 0 && (
              <details className="reviewed-disclosure">
                <summary>
                  <Icon name="chevron-right" size={14} className="disclosure-chevron" />
                  Reviewed ({brief.done.length})
                </summary>
                <ul className="review-list">
                  {brief.done.map((set) => (
                    <ReviewItem key={set.file_id} set={set} summary={summaryOf(set)} since={since} onToggle={toggleReviewed} done />
                  ))}
                </ul>
              </details>
            )}
          </section>

          <section className="card" aria-labelledby="activity-title">
            <div className="card-head">
              <div>
                <h2 id="activity-title">Change activity</h2>
                <p className="card-sub">Every analysed change to a monitored source over the last six months.</p>
              </div>
              <Link to="/policies" className="card-link">
                Policy watch <Icon name="arrow-right" size={14} />
              </Link>
            </div>
            {history.error ? (
              <p className="muted">{history.error}</p>
            ) : (
              <ChangeTimeline policySets={policySets} entries={history.entries} days={182} />
            )}
          </section>

          <section className="card" aria-labelledby="incidents-title">
            <div className="card-head">
              <div>
                <h2 id="incidents-title">AI incidents in Australia</h2>
                <p className="card-sub">From the OECD AI Incidents Monitor, last {RECENT_DAYS} days.</p>
              </div>
              <Link to="/incidents" className="card-link">
                All incidents <Icon name="arrow-right" size={14} />
              </Link>
            </div>
            {brief.localIncidents.length === 0 ? (
              <p className="muted">No AI incidents recorded in Australia in the last {RECENT_DAYS} days.</p>
            ) : (
              <div className="compact-feed">
                {brief.localIncidents.map((item) => (
                  <FeedCard key={item.id} item={item} since={since} policyNames={policyNames} compact />
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="overview-col">
          <section className="card" aria-labelledby="coverage-title">
            <div className="card-head">
              <div>
                <h2 id="coverage-title">Coverage</h2>
                <p className="card-sub">Whether each monitored source was actually read.</p>
              </div>
              <Link to="/sources" className="card-link">
                Sources <Icon name="arrow-right" size={14} />
              </Link>
            </div>
            {brief.failingSources.length > 0 && (
              <ul className="coverage-alerts">
                {brief.failingSources.map((source) => (
                  <li key={source.file_id || source.setName} className={`coverage-alert ${source.status}`}>
                    <Icon name="alert" size={16} />
                    <div>
                      <Link to={`/policy/${source.file_id}`}>{source.setName}</Link>
                      <p>{failingMessage(source)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <p className="stable-line">
              <Icon name="check-circle" size={15} />
              {brief.stable.length} of {totalSources} checked and unchanged for {RECENT_DAYS} days
            </p>
            <ul className="chip-list">
              {brief.stable.map((set) => (
                <li key={set.file_id}>
                  <Link className="source-chip" to={`/policy/${set.file_id}`}>
                    <Lettermark url={primaryUrl(set)} name={set.setName} size={16} />
                    <span>{set.setName}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          {brief.adoption.length > 0 && (
            <section className="card" aria-labelledby="adoption-title">
              <div className="card-head">
                <div>
                  <h2 id="adoption-title">Across government</h2>
                  <p className="card-sub">How other agencies are adopting AI. For awareness — nothing here needs review.</p>
                </div>
              </div>
              <ul className="review-list">
                {brief.adoption.map((set) => (
                  <AdoptionItem key={set.file_id} set={set} summary={summaryOf(set)} since={since} />
                ))}
              </ul>
            </section>
          )}

          <section className="card" aria-labelledby="news-title">
            <div className="card-head">
              <div>
                <h2 id="news-title">Top stories this week</h2>
                <p className="card-sub">The most relevant news for APS work.</p>
              </div>
              <Link to="/news" className="card-link">
                All news <Icon name="arrow-right" size={14} />
              </Link>
            </div>
            {brief.topNews.length === 0 ? (
              <p className="muted">
                {feed?.items?.length ? 'No relevant news in the last seven days.' : 'The news feed has not run yet.'}
              </p>
            ) : (
              <div className="compact-feed">
                {brief.topNews.map((item) => (
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
