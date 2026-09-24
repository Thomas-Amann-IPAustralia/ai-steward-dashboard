import React from 'react';
import { Link } from 'react-router-dom';
import {
  changeSummaryOf,
  formatRelative,
  PRIORITY_DESCRIPTIONS,
  PRIORITY_ORDER,
  primaryUrl,
  timestampOf,
} from '../utils/constants';
import Lettermark from './Lettermark';
import PriorityBadge from './PriorityBadge';
import { HealthPill } from './SourceHealth';

/**
 * Every monitored policy set at a glance, most recently changed first, with
 * the guide to what the priorities mean. On a phone this is the policy list.
 */
function PoliciesOverview({ policySets, health, loading }) {
  const healthSources = health?.sources || {};
  const sets = [...policySets].sort((a, b) => timestampOf(b.last_amended) - timestampOf(a.last_amended));

  return (
    <div className="policies-overview">
      <div className="page-header">
        <div>
          <h2>Policy watch</h2>
          <p className="page-subtitle">
            {policySets.length} policy sets — government AI policy and the terms of AI services APS staff
            use — checked every day for changes in wording.
          </p>
        </div>
      </div>

      {loading && policySets.length === 0 && <div className="loading-message">Loading policies…</div>}

      <ul className="policy-cards">
        {sets.map((set) => {
          const summary = changeSummaryOf(set);
          const status = healthSources[set.setName]?.status || set.status || 'ok';
          return (
            <li key={set.file_id} className="policy-card">
              <div className="briefing-item-head">
                <Lettermark url={primaryUrl(set)} name={set.setName} />
                <Link className="briefing-item-name" to={`/policy/${set.file_id}`}>
                  {set.setName}
                </Link>
                <PriorityBadge priority={set.last_priority} date={set.last_amended} />
                <HealthPill status={status} />
              </div>
              {summary && <p className="briefing-item-summary">{summary}</p>}
              <div className="briefing-item-meta">
                <span>{set.category}</span>
                <span>
                  {set.last_amended ? `Last material change ${formatRelative(set.last_amended)}` : 'No change recorded'}
                </span>
              </div>
            </li>
          );
        })}
      </ul>

      <aside className="legend">
        <h3>What the priorities mean</h3>
        <dl>
          {PRIORITY_ORDER.map((priority) => (
            <React.Fragment key={priority}>
              <dt><PriorityBadge priority={priority} solid /></dt>
              <dd>{PRIORITY_DESCRIPTIONS[priority]}</dd>
            </React.Fragment>
          ))}
        </dl>
        <p>
          A priority describes a change, not the document, and it fades after 30 days. A change
          that turns out to be only formatting, or a page flipping between two versions, is
          filtered out before it can be rated at all.
        </p>
      </aside>
    </div>
  );
}

export default PoliciesOverview;
