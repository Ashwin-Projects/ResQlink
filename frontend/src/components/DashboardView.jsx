import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { FileText, Boxes, Lock, CheckCircle2, RefreshCw, Activity, Workflow, ArrowRight } from 'lucide-react';
import { PageHeader, Panel, StatTile, SegmentBar, LoadingState, ErrorState, EmptyState, Badge } from './ui';
import { describeAuditEvent } from './auditFormat';
import { fmtQty, fmtClock, relativeTime, short, STAGE_LABELS } from './format';
import { RESOURCE_TYPE_LABELS, STATUS_LABELS, label } from './resourceLabels';

// Every number on this page comes from GET /api/v1/dashboard/stats, which counts
// rows under the caller's PostgreSQL role (RLS). Sections a role cannot see come
// back as null and are shown as "—" with an explanation; nothing is estimated.
const ROLE_SCOPE = {
  coordinator: 'All zones · coordinator view. Counts are read live from PostgreSQL.',
  owner: 'Your organisation’s resources. Counts are read live from PostgreSQL under your role.',
  requester: 'Your requests and the resources currently available. Counts are read live from PostgreSQL under your role.',
};

const na = (v) => (v === null || v === undefined ? '—' : fmtQty(v));

function RecentActivity({ role, onNavigate, allowedTabs }) {
  const [state, setState] = useState({ status: 'loading' });
  const load = useCallback(async () => {
    setState({ status: 'loading' });
    try {
      if (role === 'coordinator') setState({ status: 'ready', kind: 'audit', items: (await api.getActivityFeed(8)).feed || [] });
      else if (role === 'requester') setState({ status: 'ready', kind: 'requests', items: await api.listEmergencyRequests({ limit: 6 }) });
      else setState({ status: 'ready', kind: 'resources', items: await api.listResourcesLive({ limit: 6 }) });
    } catch (err) {
      setState({ status: 'error', error: err.message });
    }
  }, [role]);
  useEffect(() => { load(); }, [load]);

  const title = role === 'coordinator' ? 'Recent activity' : role === 'requester' ? 'Your latest requests' : 'Recently updated resources';
  const target = role === 'coordinator' ? 'audit' : role === 'requester' ? 'requests' : 'resources';
  const subtitle = role === 'coordinator' ? 'Latest audit log entries' : 'Live from PostgreSQL';

  return (
    <Panel title={title} subtitle={subtitle} icon={Activity}
           actions={allowedTabs.includes(target) && (
             <button type="button" className="btn btn-ghost btn-sm" onClick={() => onNavigate(target)} aria-label="View all activity">
               View all <ArrowRight size={13} />
             </button>
           )}>
      {state.status === 'loading' && <LoadingState compact label="Loading activity…" />}
      {state.status === 'error' && <ErrorState compact title="Unable to load recent activity" message={state.error} onRetry={load} />}
      {state.status === 'ready' && state.items.length === 0 && (
        <EmptyState compact title="Nothing yet" message={role === 'requester' ? 'You have not submitted any requests.' : 'No activity recorded yet.'} />
      )}
      {state.status === 'ready' && state.items.length > 0 && (
        <div>
          {state.kind === 'audit' && state.items.map(log => {
            const e = describeAuditEvent(log);
            return (
              <div className="activity-row" key={log.log_id}>
                <span className="activity-time" title={new Date(log.performed_at).toLocaleString()}>{fmtClock(log.performed_at).slice(0, 5)}</span>
                <div className="activity-text">
                  <div>{e.title}</div>
                  <div className="activity-sub">{e.entity}{e.remarks ? ` · ${e.remarks}` : ''}</div>
                </div>
              </div>
            );
          })}
          {state.kind === 'requests' && state.items.map(r => (
            <div className="activity-row" key={r.request_id}>
              <span className="activity-time">{relativeTime(r.requested_at)}</span>
              <div className="activity-text">
                <div className="chip-row">
                  <span>{fmtQty(r.quantity_requested)} × {label(RESOURCE_TYPE_LABELS, r.resource_type_needed)}</span>
                  <Badge value={r.tracking_stage || r.status}>{STAGE_LABELS[r.tracking_stage || r.status] || r.status}</Badge>
                </div>
                <div className="activity-sub">{r.zone_name} · {fmtQty(r.quantity_fulfilled)} of {fmtQty(r.quantity_requested)} fulfilled · {short(r.request_id)}</div>
              </div>
            </div>
          ))}
          {state.kind === 'resources' && state.items.map(r => (
            <div className="activity-row" key={r.resource_id}>
              <span className="activity-time">{relativeTime(r.updated_at)}</span>
              <div className="activity-text">
                <div className="chip-row">
                  <span>{label(RESOURCE_TYPE_LABELS, r.resource_type)}{r.resource_subtype ? ` · ${r.resource_subtype}` : ''}</span>
                  <Badge value={r.status}>{label(STATUS_LABELS, r.status)}</Badge>
                </div>
                <div className="activity-sub">{fmtQty(r.quantity_available)} / {fmtQty(r.quantity_total)} {r.unit_of_measure} available · {r.zone_name}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function Overview({ title, subtitle, icon, segments, hiddenNote }) {
  const total = segments.reduce((s, x) => s + (Number(x.value) || 0), 0);
  return (
    <Panel title={title} subtitle={subtitle} icon={icon}>
      {hiddenNote ? (
        <EmptyState compact title="Not visible to your role" message={hiddenNote} />
      ) : total === 0 ? (
        <EmptyState compact title="No records yet" message="Counts appear here as soon as rows exist in the database." />
      ) : (
        <>
          <SegmentBar segments={segments} label={`${title}: ${segments.map(s => `${s.label} ${s.value}`).join(', ')}`} />
          <div className="legend-list">
            {segments.map(s => (
              <div className="legend-item" key={s.key}>
                <span><span className={`legend-dot tone-${s.tone}`} />{s.label}</span>
                <strong>{fmtQty(s.value)}</strong>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

export default function DashboardView({ onNavigate, allowedTabs = [], role }) {
  const [stats, setStats] = useState(null);
  const [state, setState] = useState('loading');
  const [error, setError] = useState(null);
  const [loadedAt, setLoadedAt] = useState(null);

  const load = useCallback(async () => {
    setState(s => (s === 'ready' ? 'refreshing' : 'loading'));
    try {
      setStats(await api.getDashboardStats());
      setError(null);
      setState('ready');
      setLoadedAt(new Date().toISOString());
    } catch (err) {
      setError(err.message);   // never replaced by demo data
      setState('error');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const scope = stats?.scope || role;
  const hidden = `Not visible to the ${scope} role`;
  const res = stats?.resources;
  const req = stats?.requests;
  const openRequests = req ? Number(req.pending || 0) + Number(req.partially_fulfilled || 0) : null;

  return (
    <div>
      <PageHeader
        eyebrow="Operations overview"
        title="Dashboard"
        subtitle={ROLE_SCOPE[role] || 'Live operational status.'}
        actions={(
          <>
            {loadedAt && <span className="live-indicator"><span className="pulse-dot" /> Updated {fmtClock(loadedAt)}</span>}
            <button type="button" className="btn btn-secondary" onClick={load} disabled={state === 'loading' || state === 'refreshing'}>
              <RefreshCw size={14} className={state === 'refreshing' ? 'spin' : undefined} /> Refresh
            </button>
          </>
        )}
      />

      {state === 'loading' && <Panel><LoadingState label="Loading live counts from PostgreSQL…" /></Panel>}
      {state === 'error' && <ErrorState title="Unable to load dashboard statistics" message={error} onRetry={load} />}

      {stats && state !== 'error' && state !== 'loading' && (
        <div className="stack">
          <div className="grid-4">
            <StatTile label="Open requests" icon={FileText} tone="amber" testId="stat-open-requests"
                      value={na(openRequests)}
                      hint={req ? `${fmtQty(req.pending)} pending · ${fmtQty(req.partially_fulfilled)} partial · ${fmtQty(req.urgent)} urgent` : hidden} />
            <StatTile label="Available resources" icon={Boxes} tone="green" testId="stat-available-resources"
                      value={na(res?.available)}
                      hint={res ? `of ${fmtQty(res.total)} registered` : hidden} />
            <StatTile label="Active reservations" icon={Lock} tone="blue" testId="stat-active-reservations"
                      value={na(stats.active_reservations)}
                      hint={stats.active_reservations == null ? hidden
                        : `leased, not yet allocated · ${fmtQty(stats.active_allocations)} allocations recorded`} />
            <StatTile label="Fulfilled requests" icon={CheckCircle2} tone="violet" testId="stat-fulfilled"
                      value={na(req?.fulfilled)}
                      hint={req ? `of ${fmtQty(req.total)} requests in total` : hidden} />
          </div>

          <div className="grid-3" style={{ alignItems: 'start' }}>
            <Overview title="Request status" subtitle="emergency_requests by status" icon={FileText}
                      hiddenNote={req ? null : 'Resource owners have no access to emergency requests.'}
                      segments={req ? [
                        { key: 'pending', label: 'Pending / open', value: Number(req.pending || 0), tone: 'amber' },
                        { key: 'partial', label: 'Partially fulfilled', value: Number(req.partially_fulfilled || 0), tone: 'violet' },
                        { key: 'fulfilled', label: 'Fulfilled', value: Number(req.fulfilled || 0), tone: 'green' },
                        { key: 'other', label: 'Cancelled / expired', value: Math.max(0, Number(req.total || 0) - Number(req.pending || 0) - Number(req.partially_fulfilled || 0) - Number(req.fulfilled || 0)), tone: 'gray' },
                      ] : []} />
            <Overview title="Resource availability" subtitle="resources by status" icon={Boxes}
                      hiddenNote={res ? null : 'Resource counts are not visible to this role.'}
                      segments={res ? [
                        { key: 'available', label: 'Available', value: Number(res.available || 0), tone: 'green' },
                        { key: 'other', label: 'Allocated / maintenance / other', value: Number(res.allocated || 0), tone: 'blue' },
                        { key: 'depleted', label: 'Depleted / unavailable', value: Number(res.depleted || 0), tone: 'red' },
                      ] : []} />
            <RecentActivity role={role} onNavigate={onNavigate} allowedTabs={allowedTabs} />
          </div>

          {role === 'coordinator' && (
            <Panel title="Coordination workflow" subtitle="Each step opens the page where it happens" icon={Workflow}>
              <div className="pipeline">
                {[
                  { k: 'Requests', t: 'Review the queue', v: `${na(openRequests)} open`, tab: 'requests', a: 'Go to the request queue' },
                  { k: 'Matching', t: 'Lease best resources', v: 'spatial retrieval + scoring', tab: 'matching', a: 'Go to candidate scoring' },
                  { k: 'Reservations', t: 'Allocate leases', v: `${na(stats.active_reservations)} active leases`, tab: 'matching', a: 'Go to lease allocation' },
                  { k: 'Delivery', t: 'Dispatch & confirm', v: `${na(req?.fulfilled)} fulfilled`, tab: 'requests', a: 'Go to delivery tracking' },
                  { k: 'Audit', t: 'Verify the trail', v: 'append-only log', tab: 'audit', a: 'Go to the audit log' },
                ].map(n => (
                  <button key={n.k} type="button" className="pipeline-node" style={{ textAlign: 'left', cursor: 'pointer', color: 'inherit', font: 'inherit' }}
                          onClick={() => onNavigate(n.tab)} aria-label={n.a}>
                    <div className="pipeline-kicker">{n.k}</div>
                    <div className="pipeline-title">{n.t}</div>
                    <div className="pipeline-value">{n.v}</div>
                  </button>
                ))}
              </div>
            </Panel>
          )}
        </div>
      )}
    </div>
  );
}
