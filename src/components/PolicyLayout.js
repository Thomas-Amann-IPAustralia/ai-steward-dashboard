import React from 'react';
import { Outlet, useMatch } from 'react-router-dom';
import Sidebar from './Sidebar';

/**
 * Policy watch: the list of monitored sets beside the selected one.
 *
 * The sidebar used to sit on every page, which on a phone put the entire
 * policy list above the briefing. It now belongs to the policy pages only,
 * and on a narrow screen it steps aside once a policy is open.
 */
function PolicyLayout({ policySets, health, loading, error }) {
  const selected = useMatch('/policy/:fileId');

  return (
    <div className={`policy-layout${selected ? ' has-selection' : ''}`}>
      <Sidebar policySets={policySets} health={health} loading={loading} error={error} />
      <div className="policy-main">
        <Outlet />
      </div>
    </div>
  );
}

export default PolicyLayout;
