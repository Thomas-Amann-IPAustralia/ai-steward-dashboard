import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  formatDate,
  formatRelative,
  primaryUrl,
  timestampOf,
} from '../utils/constants';
import { buildBriefing, copyToClipboard } from '../utils/briefing';
import Lettermark from './Lettermark';
import PriorityBadge from './PriorityBadge';
import { HealthPill } from './SourceHealth';

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;
const ATTENTION_PRIORITIES = new Set(['critical', 'high']);

/**
 * A briefing, not a stat wall.
 *
 * Four counters and an undated list did not answer the question a steward
 * actually arrives with on a Monday morning: what changed since I last looked,
 * why does it matter, and what needs action. The order below is that question,
 * and "all stable" is information too — it is stated deliberately rather than
 * shown as an empty region.
 */
function DashboardHome({ policySets, health }) {
  const navigate = useNavigate();
  const [copied, setCopied] = useState(null);

  const open = (fileId) => navigate(`/policy/${fileId}`);
  const keyActivate = (event, fileId) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      open(fileId);
    }
  };

  const brief = useMemo(() => {
    const cutoff = Date.now() - SEVEN_DAYS_MS;
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
      }))
      .sort((a, b) => (a.status === 'failing' ? -1 : 1));

    const recentChanges = withHealth
      .filter((set) => timestampOf(set.last_amended) > cutoff)
      .sort((a, b) => timestampOf(b.last_amended) - timestampOf(a.last_amended));

    const needsAttention = recentChanges.filter((set) =>
      ATTENTION_PRIORITIES.has((set.last_priority || '').toLowerCase())
    );
    const otherChanges = recentChanges.filter(
      (set) => !ATTENTION_PRIORITIES.has((set.last_priority || '').toLowerCase())
    );

    const stable = withHealth.filter(
      (set) => timestampOf(set.last_amended) <= cutoff && set.health.status === 'ok'
    );

    const lastScan = withHealth.reduce(
      (latest, set) => Math.max(latest, timestampOf(set.last_checked)),
      0
    );

    return {
      withHealth,
      failingSources,
      recentChanges,
      needsAttention,
      otherChanges,
      stable,
      lastScan,
    };
  }, [policySets, health]);

  const copyBriefing = async () => {
    const ok = await copyToClipboard(
      buildBriefing({
        recentChanges: brief.recentChanges,
        failingSources: brief.failingSources,
        stableCount: brief.stable.length,
      })
    );
    setCopied(ok ? 'Copied to clipboard' : 'Could not copy — select and copy manually');
    setTimeout(() => setCopied(null), 4000);
  };

  const changeRow = (set) => (
    <li
      key={set.file_id}
      className="briefing-item"
      onClick={() => open(set.file_id)}
      onKeyDown={(event) => keyActivate(event, set.file_id)}
      tabIndex={0}
      role="button"
    >
      <div className="briefing-item-head">
        <Lettermark url={primaryUrl(set)} name={set.setName} />
        <span className="briefing-item-name">{set.setName}</span>
        <PriorityBadge priority={set.last_priority} date={set.last_amended} solid />
        <HealthPill status={set.health?.status} />
      </div>
      {set.last_review?.summary && (
        <p className="briefing-item-summary">{set.last_review.summary}</p>
      )}
      <div className="briefing-item-meta">
        {set.last_change?.changed_documents?.length > 0 && (
          <span className="changed-documents">
            {set.last_change.changed_documents.join(', ')}
          </span>
        )}
        <span>Changed {formatRelative(set.last_amended)}</span>
      </div>
    </li>
  );

  return (
    <div className="dashboard-home">
      <div className="briefing-header">
        <div>
          <h2>Policy briefing</h2>
          <p className="briefing-subtitle">
            {brief.lastScan
              ? `Last checked ${formatDate(new Date(brief.lastScan).toISOString())}`
              : 'No completed scan recorded yet'}
            {' · '}
            {policySets.length} policy set{policySets.length === 1 ? '' : 's'} monitored
          </p>
        </div>
        <div className="briefing-actions">
          <button type="button" className="secondary-button" onClick={copyBriefing}>
            Copy 7-day briefing
          </button>
          <span className="copy-feedback" role="status" aria-live="polite">
            {copied}
          </span>
        </div>
      </div>

      {(brief.needsAttention.length > 0 || brief.failingSources.length > 0) && (
        <section className="briefing-section attention">
          <h3>Needs attention</h3>

          {brief.failingSources.length > 0 && (
            <ul className="briefing-list">
              {brief.failingSources.map((source) => (
                <li
                  key={source.file_id || source.setName}
                  className="briefing-item failing"
                  onClick={() => open(source.file_id)}
                  onKeyDown={(event) => keyActivate(event, source.file_id)}
                  tabIndex={0}
                  role="button"
                >
                  <div className="briefing-item-head">
                    <span className="briefing-item-name">{source.setName}</span>
                    <HealthPill status={source.status} />
                  </div>
                  <p className="briefing-item-summary">
                    {source.status === 'failing'
                      ? 'This source has failed repeatedly. "No changes" here means "not checked".'
                      : 'The last read of this source failed. The stored snapshot was left untouched.'}
                    {source.last_success
                      ? ` Last complete read ${formatRelative(source.last_success)}.`
                      : ' It has never been read successfully.'}
                  </p>
                </li>
              ))}
            </ul>
          )}

          {brief.needsAttention.length > 0 && (
            <ul className="briefing-list">{brief.needsAttention.map(changeRow)}</ul>
          )}
        </section>
      )}

      <section className="briefing-section">
        <h3>This week's changes</h3>
        {brief.recentChanges.length === 0 ? (
          <p className="briefing-quiet">
            No policy changes detected in the last seven days.
          </p>
        ) : brief.otherChanges.length > 0 ? (
          <ul className="briefing-list">{brief.otherChanges.map(changeRow)}</ul>
        ) : (
          <p className="briefing-quiet">
            Everything that changed this week is listed under “Needs attention” above.
          </p>
        )}
      </section>

      <section className="briefing-section stable">
        <h3>Checked and unchanged</h3>
        <p className="briefing-quiet">
          {brief.stable.length} of {policySets.length} monitored policy sets were checked
          and showed no material change.
        </p>
        <ul className="stable-chips">
          {brief.stable.map((set) => (
            <li key={set.file_id}>
              <button type="button" className="stable-chip" onClick={() => open(set.file_id)}>
                <Lettermark url={primaryUrl(set)} name={set.setName} size={14} />
                <span>{set.setName}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export default DashboardHome;
