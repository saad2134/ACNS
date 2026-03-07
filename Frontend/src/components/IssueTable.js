/**
 * components/IssueTable.js
 * ---------------------------------------------------------------
 * Renders a table of accessibility issues.
 *
 * Props:
 *   issues  – array of { id, location, issueType, status, reportedAt }
 *   loading – boolean
 * ---------------------------------------------------------------
 */

import React from 'react';

const statusBadge = (s) => {
  const lower = (s || '').toLowerCase();
  if (lower === 'resolved') return <span className="badge-acns badge-resolved">Resolved</span>;
  if (lower === 'pending')  return <span className="badge-acns badge-pending">Pending</span>;
  return <span className="badge-acns badge-open">Open</span>;
};

const IssueTable = ({ issues = [], loading = false }) => {
  if (loading) {
    return (
      <div className="text-center py-5" style={{ color: 'var(--text-secondary)' }}>
        <div className="spinner-border text-info" role="status" />
        <p className="mt-3">Loading issues…</p>
      </div>
    );
  }

  if (issues.length === 0) {
    return (
      <div className="text-center py-5" style={{ color: 'var(--text-secondary)' }}>
        No issues found.
      </div>
    );
  }

  return (
    <div className="glass-card p-0 overflow-hidden animate-in">
      <div style={{ overflowX: 'auto' }}>
        <table className="table-acns">
          <thead>
            <tr>
              <th>#</th>
              <th>Location</th>
              <th>Issue Type</th>
              <th>Status</th>
              <th>Reported</th>
            </tr>
          </thead>
          <tbody>
            {issues.map((issue, i) => (
              <tr key={issue.id || i}>
                <td style={{ color: 'var(--text-secondary)' }}>{issue.report_id || issue.id || i + 1}</td>
                <td style={{ fontWeight: 500 }}>
                  {typeof issue.location === 'object' && issue.location !== null 
                    ? (issue.location.building || issue.location.campus_zone || `${issue.location.latitude}, ${issue.location.longitude}`)
                    : issue.location}
                </td>
                <td>{issue.category || issue.issueType}</td>
                <td>{statusBadge(issue.status)}</td>
                <td style={{ color: 'var(--text-secondary)', fontSize: '.85rem' }}>
                  {issue.created_at || issue.reportedAt
                    ? new Date(issue.created_at || issue.reportedAt).toLocaleDateString()
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default IssueTable;
