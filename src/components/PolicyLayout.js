import React from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';

/**
 * An open policy beside the list of every monitored set, so a steward can
 * work down the list without going back. On a narrow screen the list steps
 * aside and the page's breadcrumb leads back to Policy watch instead.
 */
function PolicyLayout({ policySets, health, loading, error }) {
  return (
    <div className="master-detail">
      <Sidebar policySets={policySets} health={health} loading={loading} error={error} />
      <div className="detail-pane">
        <Outlet />
      </div>
    </div>
  );
}

export default PolicyLayout;
