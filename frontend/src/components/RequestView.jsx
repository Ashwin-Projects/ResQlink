import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import { FileText, CheckCircle2, GitMerge, RefreshCw, Activity, Plus, X } from 'lucide-react';
import CreateRequestForm from './CreateRequestForm';
import RequestTrackingPanel from './RequestTrackingPanel';
import { PageHeader, Panel, Badge, LoadingState, ErrorState, EmptyState } from './ui';
import { fmtQty, relativeTime, pct, STAGE_LABELS, URGENCY_LABELS } from './format';
import { phaseFromRow, nextStepFromRow } from './lifecycle';
import { RESOURCE_TYPE_LABELS, label } from './resourceLabels';

const LIST_LIMIT = 200;
// Background refresh of the queue so status/quantity changes made elsewhere
// (matching engine, allocation updates, workers) appear without a reload.
const LIST_REFRESH_MS = 15000;
const TERMINAL = ['fulfilled', 'cancelled', 'expired'];

function PhaseCell({ row }) {
  const phase = phaseFromRow(row);
  return (
    <div className="phase" title={`Lifecycle: ${phase.label}`}>
      <div className="chip-row">
        <Badge value={row.tracking_stage || row.status}>{STAGE_LABELS[row.tracking_stage || row.status] || row.status}</Badge>
      </div>
      <div className={`phase-track tone-${phase.tone}`} aria-hidden="true">
        {[0, 1, 2, 3, 4, 5].map(i => <span key={i} className={i <= phase.index ? 'on' : ''} />)}
      </div>
      <div className="cell-sub" style={{ marginTop: 0 }}>{phase.label}</div>
    </div>
  );
}

export default function RequestView({ onMatchSelect, role }) {
  const [requests, setRequests] = useState([]);
  const [listState, setListState] = useState('loading'); // loading | ready | error
  const [listError, setListError] = useState(null);
  const [urgencyFilter, setUrgencyFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [newRequestIds, setNewRequestIds] = useState(() => new Set());
  const [trackedId, setTrackedId] = useState(null);
  const [showForm, setShowForm] = useState(role === 'requester');
  const trackingRef = useRef(null);
  const canManage = !!onMatchSelect;

  // Live list from GET /api/v1/requests (PostgreSQL, newest first). No
  // fallback data: if the API is unreachable the page says so.
  const loadRequests = useCallback(async ({ silent = false } = {}) => {
    if (!silent) {
      setListState('loading');
      setListError(null);
    }
    try {
      const data = await api.listEmergencyRequests({ limit: LIST_LIMIT });
      setRequests(data);
      setListState('ready');
      setListError(null);
    } catch (err) {
      setListError(err.message);
      // A failed background refresh keeps the last list that came from the API.
      if (!silent) setListState('error');
    }
  }, []);

  useEffect(() => { loadRequests(); }, [loadRequests]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') loadRequests({ silent: true });
    }, LIST_REFRESH_MS);
    return () => clearInterval(timer);
  }, [loadRequests]);

  // The tracking panel re-reads one request every few seconds; keep its row in sync.
  const handleTrackingUpdate = useCallback((fresh) => {
    setRequests(prev => prev.map(r => (r.request_id === fresh.request_id ? { ...r, ...fresh } : r)));
  }, []);

  const track = (id) => {
    setTrackedId(id);
    requestAnimationFrame(() => trackingRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  // Called with the created request returned by POST /api/v1/requests.
  const handleCreated = useCallback((created) => {
    setRequests(prev => [created, ...prev.filter(r => r.request_id !== created.request_id)]);
    setNewRequestIds(prev => new Set(prev).add(created.request_id));
    setTrackedId(created.request_id);
    // Make sure the new row is not hidden by the current filters.
    setUrgencyFilter('all');
    setStatusFilter('all');
  }, []);

  const counts = useMemo(() => {
    const c = { all: requests.length };
    requests.forEach(r => { const k = r.tracking_stage || r.status; c[k] = (c[k] || 0) + 1; });
    return c;
  }, [requests]);

  const filteredRequests = requests.filter(req => {
    const matchesUrgency = urgencyFilter === 'all' || req.urgency_level === urgencyFilter;
    const matchesStatus = statusFilter === 'all' || (req.tracking_stage || req.status) === statusFilter;
    return matchesUrgency && matchesStatus;
  });

  return (
    <div>
      <PageHeader
        eyebrow="Operations"
        title="Emergency Requests"
        subtitle={role === 'requester'
          ? 'Submit a request and follow it from Pending to Fulfilled. You only see your own requests.'
          : 'Every request in the queue with its live lifecycle stage, what it still needs and the next possible action.'}
        actions={(
          <>
            <button type="button" className="btn btn-secondary" onClick={() => loadRequests()} disabled={listState === 'loading'}>
              <RefreshCw size={14} /> Refresh
            </button>
            <button type="button" className={`btn ${showForm ? 'btn-secondary' : 'btn-emergency'}`} onClick={() => setShowForm(v => !v)} aria-expanded={showForm}>
              {showForm ? <><X size={14} /> Close form</> : <><Plus size={14} /> New request</>}
            </button>
          </>
        )}
      />

      {showForm && <CreateRequestForm onCreated={handleCreated} onClose={() => setShowForm(false)} />}

      <div ref={trackingRef} style={{ scrollMarginTop: 16 }}>
        {trackedId && (
          <div style={{ marginBottom: 16 }}>
            <RequestTrackingPanel
              key={trackedId}
              requestId={trackedId}
              onClose={() => setTrackedId(null)}
              onUpdate={handleTrackingUpdate}
            />
          </div>
        )}
      </div>

      <Panel flush icon={FileText} title="Request queue"
             subtitle={<>Live from <code>emergency_requests</code> · newest first · auto-refresh every {LIST_REFRESH_MS / 1000}s
               {listState === 'ready' && listError && <span style={{ color: '#ff8b8b' }}> · last refresh failed, showing previous data</span>}</>}
             actions={(
               <div className="toolbar">
                 <div className="segmented" role="group" aria-label="Filter by stage">
                   {[['all', 'All'], ['pending', 'Pending'], ['matching', 'Matching'], ['partially_fulfilled', 'Partial'], ['fulfilled', 'Fulfilled']].map(([k, l]) => (
                     <button key={k} type="button" aria-pressed={statusFilter === k} onClick={() => setStatusFilter(k)}>
                       {l} <span className="count">{counts[k] || 0}</span>
                     </button>
                   ))}
                 </div>
                 <select className="form-select" aria-label="Filter by urgency" value={urgencyFilter} onChange={e => setUrgencyFilter(e.target.value)}>
                   <option value="all">All urgencies</option>
                   {Object.entries(URGENCY_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                 </select>
               </div>
             )}>
        {listState === 'loading' && <LoadingState label="Loading request queue…" />}

        {listState === 'error' && (
          <ErrorState title="Unable to load requests" message={`Could not load emergency requests. ${listError || ''}`} onRetry={() => loadRequests()} />
        )}

        {listState === 'ready' && requests.length === 0 && (
          <EmptyState icon={FileText} title="No emergency requests yet"
                      message="Requests appear here as soon as they are stored in PostgreSQL."
                      action={!showForm && <button type="button" className="btn btn-sm" onClick={() => setShowForm(true)}><Plus size={13} /> New request</button>} />
        )}

        {listState === 'ready' && requests.length > 0 && filteredRequests.length === 0 && (
          <EmptyState compact title="No requests match the selected filters" />
        )}

        {listState === 'ready' && filteredRequests.length > 0 && (
          <div className="table-container">
            <table className="data-table" aria-label="Emergency request queue">
              <thead>
                <tr>
                  <th>Request</th>
                  <th>Need</th>
                  <th>Urgency</th>
                  <th>Fulfilment</th>
                  <th>Stage</th>
                  <th>Next step</th>
                  <th className="right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredRequests.map((req) => {
                  const isNew = newRequestIds.has(req.request_id);
                  const isTracked = trackedId === req.request_id;
                  const remaining = req.quantity_remaining ?? Math.max(0, req.quantity_requested - req.quantity_fulfilled);
                  return (
                    <tr key={req.request_id} className={isTracked ? 'row-selected' : isNew ? 'row-new' : undefined}>
                      <td title={req.request_id}>
                        <div className="cell-id">{req.request_id.substring(0, 18)}…</div>
                        <div className="cell-sub">{relativeTime(req.requested_at)} · {req.zone_name || '—'}</div>
                        {isNew && <div style={{ marginTop: 4 }}><Badge value="available" dot={false}>new</Badge></div>}
                      </td>
                      <td style={{ maxWidth: 280 }}>
                        <div className="cell-main">{label(RESOURCE_TYPE_LABELS, req.resource_type_needed)}</div>
                        {req.description && <div className="cell-sub" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={req.description}>{req.description}</div>}
                      </td>
                      <td><span className={`urgency urgency-${req.urgency_level}`}>{req.urgency_level}</span></td>
                      <td>
                        <div className="num"><strong>{fmtQty(req.quantity_fulfilled)}</strong> / {fmtQty(req.quantity_requested)}</div>
                        <div className="qbar" aria-hidden="true">
                          <span className="seg-fulfilled" style={{ width: `${pct(req.quantity_fulfilled, req.quantity_requested)}%` }} />
                          <span className="seg-in-progress" style={{ width: `${pct(Math.min(req.quantity_in_progress || 0, remaining), req.quantity_requested)}%` }} />
                          <span className="seg-reserved" style={{ width: `${pct(Math.min(req.quantity_reserved || 0, Math.max(0, remaining - (req.quantity_in_progress || 0))), req.quantity_requested)}%` }} />
                        </div>
                        {req.quantity_remaining != null && <div className="cell-sub">{fmtQty(req.quantity_remaining)} remaining</div>}
                      </td>
                      <td>
                        <PhaseCell row={req} />
                        {(req.tracking_stage || req.status) !== req.status && <div className="cell-sub">db: {req.status}</div>}
                      </td>
                      <td className="next-step" style={{ maxWidth: 200 }}>{nextStepFromRow(req, canManage)}</td>
                      <td className="actions">
                        <div className="btn-group" style={{ justifyContent: 'flex-end' }}>
                          <button type="button" className="btn btn-secondary btn-sm" onClick={() => track(req.request_id)} aria-pressed={isTracked}>
                            <Activity size={13} /> Track
                          </button>
                          {!TERMINAL.includes(req.status) && onMatchSelect && (
                            <button type="button" className="btn btn-sm" onClick={() => onMatchSelect(req)}>
                              <GitMerge size={13} /> Match
                            </button>
                          )}
                          {req.status === 'fulfilled' && (
                            <span className="text-3" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--green)' }}>
                              <CheckCircle2 size={14} /> Complete
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
