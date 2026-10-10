import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { Activity, Clock, RefreshCw, X, Loader2, AlertTriangle, History, Truck, Lock, Zap, Search, CheckCircle2, Send, ArrowRight } from 'lucide-react';
import { Badge, StepFlow, LoadingState, EmptyState, KeyValue } from './ui';
import { fmtQty, fmtTime, pct, relativeTime, short, STAGE_LABELS, ALLOCATION_STATUS_LABELS } from './format';
import { lifecycleFromTracking, nextStepFromTracking } from './lifecycle';
import { RESOURCE_TYPE_LABELS, label } from './resourceLabels';

export { STAGE_LABELS };

// Polling interval for live tracking. Every poll re-reads PostgreSQL through
// GET /api/v1/requests/{id}/tracking; nothing is cached in browser storage.
export const TRACKING_POLL_MS = 5000;

// Next allocation steps offered in the UI. The database state machine
// (fn_allocations_on_status_change) remains the authority on what is legal.
export const ALLOCATION_ACTIONS = {
  reserved:   [{ to: 'dispatched', label: 'Dispatch', primary: true }, { to: 'cancelled', label: 'Cancel', danger: true }],
  dispatched: [{ to: 'in_transit', label: 'In transit' }, { to: 'confirmed', label: 'Confirm delivery', primary: true }, { to: 'cancelled', label: 'Cancel', danger: true }],
  in_transit: [{ to: 'delivered', label: 'Mark delivered' }, { to: 'cancelled', label: 'Cancel', danger: true }],
  delivered:  [{ to: 'confirmed', label: 'Confirm delivery', primary: true }],
};

export function ScoreDetails({ components, score }) {
  if (!components && score == null) return null;
  const c = components || {};
  return (
    <div className="cell-sub">
      {score != null && <>score {Number(score).toFixed(3)}</>}
      {c.distance_m != null && <> · {(c.distance_m / 1000).toFixed(2)} km</>}
      {c.confidence != null && <> · conf {c.confidence}</>}
      {c.accessibility != null && <> · access {c.accessibility}</>}
      {c.urgency_bonus ? <> · urgency +{c.urgency_bonus}</> : null}
    </div>
  );
}

export default function RequestTrackingPanel({ requestId, onClose, onUpdate, hideMatchControls = false, embedded = false }) {
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading'); // loading | ready | error
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [lastFetched, setLastFetched] = useState(null);
  const [now, setNow] = useState(Date.now());
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(null);          // key of the action in progress
  const [actionMsg, setActionMsg] = useState(null); // { kind: 'success' | 'error', text }
  const [candidates, setCandidates] = useState(null);
  const [showCandidates, setShowCandidates] = useState(false);
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  const load = useCallback(async ({ silent = false, force = false } = {}) => {
    if (inFlight.current) {
      if (!force) return;                       // a background poll is already running
      while (inFlight.current) await new Promise(r => setTimeout(r, 50));  // after an action: wait, then re-read
    }
    inFlight.current = true;
    if (!silent) setRefreshing(true);
    try {
      const result = await api.getRequestTracking(requestId);
      setData(result);
      setState('ready');
      setError(null);
      setLastFetched(Date.now());
      onUpdateRef.current?.(result.request);
    } catch (err) {
      setError(err.status === 404 ? 'This request no longer exists or is not visible to your role.' : err.message);
      setState(prev => (prev === 'ready' ? 'ready' : 'error')); // keep last good data on a transient failure
    } finally {
      inFlight.current = false;
      setRefreshing(false);
    }
  }, [requestId]);

  useEffect(() => {
    setData(null);
    setState('loading');
    load();
  }, [load]);

  const loadCandidates = useCallback(async () => {
    try {
      setCandidates(await api.getMatchCandidates(requestId));
    } catch (err) {
      setCandidates({ error: err.message });
    }
  }, [requestId]);

  // Runs one workflow operation against the API, then re-reads the database
  // state immediately (no optimistic UI state).
  const runAction = async (key, fn, describe) => {
    if (busy) return;
    setBusy(key);
    setActionMsg(null);
    let message;
    try {
      const result = await fn();
      message = { kind: 'success', text: describe(result) };
    } catch (err) {
      message = { kind: 'error', text: err.message || 'Operation failed.' };
    }
    await load({ silent: true, force: true });
    if (showCandidates) loadCandidates();
    setBusy(null);
    setActionMsg(message);
  };

  const doMatch = () => runAction('match', () => api.matchRequest(requestId), (r) => {
    const n = r.proposed_reservations?.length || 0;
    const qty = (r.proposed_reservations || []).reduce((s, x) => s + Number(x.quantity || 0), 0);
    return n ? `Matching engine leased ${fmtQty(qty)} from ${n} resource${n > 1 ? 's' : ''} (FOR UPDATE SKIP LOCKED, 1 h lease).`
             : 'Matching ran: no available candidate resources within range, or nothing left to cover.';
  });
  const doAllocate = (v) => runAction(`alloc-${v.reservation_id}`, () => api.allocateReservation(v.reservation_id),
    (r) => `Allocation ${r.allocation.allocation_id.substring(0, 8)} created from the lease (${fmtQty(r.allocation.quantity_allocated)}, status reserved).`);
  const doRelease = (v) => runAction(`rel-${v.reservation_id}`, () => api.releaseReservation(v.reservation_id),
    () => `Lease released; ${fmtQty(v.quantity)} returned to the resource.`);
  const doTransition = (a, to) => runAction(`tr-${a.allocation_id}-${to}`, () => api.transitionAllocation(a.allocation_id, to),
    (r) => `Allocation ${a.allocation_id.substring(0, 8)}: ${r.previous_status} → ${r.allocation.allocation_status}. Request is now ${r.allocation.request_status} (${fmtQty(r.allocation.quantity_fulfilled)}/${fmtQty(r.allocation.quantity_requested)} fulfilled).`);

  // Live updates: poll while the tab is visible; refetch immediately when it becomes visible again.
  useEffect(() => {
    const tick = () => { if (document.visibilityState === 'visible') load({ silent: true }); };
    const timer = setInterval(tick, TRACKING_POLL_MS);
    const onVisible = () => { if (document.visibilityState === 'visible') load({ silent: true }); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); };
  }, [load]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const req = data?.request;
  const q = data?.quantities;
  const life = data ? lifecycleFromTracking(data) : null;
  const next = data ? nextStepFromTracking(data) : null;
  const canMatch = data?.can_manage && !data?.is_terminal && !hideMatchControls;

  return (
    <section className={`card tracking-panel ${embedded ? '' : ''}`} aria-live="polite" aria-label="Request Status Tracking">
      <div className="card-header">
        <div className="card-heading">
          <h2 className="card-title"><Activity size={16} className="card-title-icon" /> Request Status Tracking</h2>
          <div className="card-subtitle mono">{requestId}</div>
        </div>
        <div className="card-actions">
          {lastFetched && (
            <span className="live-indicator" title={`Database time ${fmtTime(data?.as_of)}`}>
              <span className="pulse-dot" /> Live · updated {relativeTime(new Date(lastFetched).toISOString(), now)}
            </span>
          )}
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => load()} disabled={refreshing} aria-label="Refresh tracking">
            {refreshing ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />} Refresh
          </button>
          {onClose && (
            <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Close tracking">
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {state === 'loading' && <LoadingState label="Loading live status from the database…" />}

      {error && (
        <div className="alert alert-error" role="alert">
          <AlertTriangle size={16} />
          <div>{state === 'ready' ? `Live update failed (showing last known state): ${error}` : `Could not load tracking: ${error}`}</div>
        </div>
      )}

      {state === 'ready' && data && (
        <>
          {/* Summary line: what is needed + current DB-derived stage */}
          <div className="chip-row" style={{ marginBottom: 14 }}>
            <Badge value={data.stage} className="stage-badge">{STAGE_LABELS[data.stage] || data.stage}</Badge>
            <span className="cell-main">{fmtQty(q.requested)} × {label(RESOURCE_TYPE_LABELS, req.resource_type_needed)}</span>
            <span className={`urgency urgency-${req.urgency_level}`}>{req.urgency_level}</span>
            <span className="text-3">{req.zone_name}</span>
            <span className="text-3">· database status <code>{data.db_status}</code>{data.is_terminal && ' · final state'}</span>
          </div>

          <StepFlow steps={life.steps} label="Request lifecycle" className="lifecycle" />

          <div className={`next-callout tone-${next.tone}`} data-testid="next-step">
            <span className="next-label">Next step</span>
            <span>{next.text}</span>
            {canMatch && (
              <div className="next-actions">
                <span className="text-3">still to cover: <strong className="num" style={{ color: 'var(--text)' }}>{fmtQty(data.quantity_to_cover)}</strong></span>
                <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy}
                        onClick={() => { const nxt = !showCandidates; setShowCandidates(nxt); if (nxt) loadCandidates(); }}>
                  <Search size={13} /> {showCandidates ? 'Hide candidates' : 'Show candidates'}
                </button>
                <button type="button" className="btn btn-sm" onClick={doMatch} disabled={!!busy || data.quantity_to_cover <= 0}
                        title={data.quantity_to_cover <= 0 ? 'Everything still needed is already reserved or allocated' : 'Run the matching engine for this request'}>
                  {busy === 'match' ? <Loader2 size={13} className="spin" /> : <Zap size={13} />} Match request
                </button>
              </div>
            )}
          </div>
          {!data.can_manage && (
            <div className="field-hint">
              Read-only: only a coordinator can match, allocate, dispatch or confirm (you are <code>{data.viewer_role}</code>).
            </div>
          )}

          {actionMsg && (
            <div className={`alert alert-${actionMsg.kind === 'success' ? 'success' : 'error'}`} role={actionMsg.kind === 'error' ? 'alert' : 'status'} style={{ marginTop: 12 }}>
              {actionMsg.kind === 'success' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
              <div className="alert-body">{actionMsg.text}</div>
              <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label="Dismiss message" onClick={() => setActionMsg(null)}><X size={12} /></button>
            </div>
          )}

          {showCandidates && (
            <div>
              <div className="tracking-section-title"><Search size={13} /> Candidate resources · live scoring, nothing reserved</div>
              {!candidates && <LoadingState compact label="Scoring candidates…" />}
              {candidates?.error && <div className="alert alert-error">{candidates.error}</div>}
              {candidates && !candidates.error && (candidates.candidates.length === 0 ? (
                <EmptyState compact title="No candidates"
                            message={`No available ${label(RESOURCE_TYPE_LABELS, req.resource_type_needed).toLowerCase()} within ${candidates.max_distance_km} km.`} />
              ) : (
                <div className="table-container">
                  <table className="data-table table-compact" aria-label="Match candidates">
                    <thead><tr><th>#</th><th>Resource</th><th>Available</th><th>Distance</th><th>Score</th></tr></thead>
                    <tbody>
                      {candidates.candidates.map((c, i) => (
                        <tr key={c.resource_id}>
                          <td className="num">{i + 1}</td>
                          <td><div>{c.resource_subtype || c.resource_type}</div><div className="cell-sub mono">{short(c.resource_id)}</div></td>
                          <td className="num">{fmtQty(c.quantity_available)} {c.unit_of_measure}</td>
                          <td className="num">{c.distance_km.toFixed(2)} km</td>
                          <td className="num">{c.score.toFixed(3)}<ScoreDetails components={c.score_components} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}

          <div className="tracking-grid">
            <div>
              <div className="tracking-section-title">Quantities</div>
              <div className="qty-bar" role="img"
                   aria-label={`${fmtQty(q.fulfilled)} of ${fmtQty(q.requested)} fulfilled, ${fmtQty(q.remaining)} remaining`}>
                <span className="seg-fulfilled" style={{ width: `${pct(q.fulfilled, q.requested)}%` }} />
                <span className="seg-in-progress" style={{ width: `${pct(Math.min(q.in_progress, q.remaining), q.requested)}%` }} />
                <span className="seg-reserved" style={{ width: `${pct(Math.min(q.reserved, Math.max(0, q.remaining - q.in_progress)), q.requested)}%` }} />
              </div>
              <div className="qty-legend">
                <span><strong style={{ color: 'var(--text)' }}>{fmtQty(q.requested)}</strong> requested</span>
                <span><span className="dot" style={{ background: 'var(--green)' }} />{fmtQty(q.fulfilled)} fulfilled</span>
                <span><strong style={{ color: 'var(--amber)' }}>{fmtQty(q.remaining)}</strong> remaining</span>
                <span><span className="dot" style={{ background: 'var(--amber)' }} />{fmtQty(q.in_progress)} allocated (in progress)</span>
                <span><span className="dot" style={{ background: 'var(--blue)' }} />{fmtQty(q.reserved)} reserved (active leases)</span>
              </div>

              <div className="tracking-section-title"><Truck size={13} /> Assigned resources</div>
              {data.allocations.length === 0 && data.reservations.length === 0 ? (
                <EmptyState compact title="No resources assigned yet"
                            message={data.can_manage ? 'Use "Match request" to lease resources for this request.' : 'A coordinator must run matching for this request.'} />
              ) : (
                <div className="table-container">
                  <table className="data-table table-compact" aria-label="Assigned resources">
                    <thead>
                      <tr><th>Type</th><th>Resource</th><th>Owner</th><th>Qty</th><th>Status</th><th>Key times / matching</th><th className="right">Actions</th></tr>
                    </thead>
                    <tbody>
                      {data.allocations.map(a => (
                        <tr key={a.allocation_id}>
                          <td><span className="tag"><Truck size={11} style={{ marginRight: 4 }} />Allocation</span></td>
                          <td><div>{a.resource_subtype || a.resource_type}</div><div className="cell-sub mono">{short(a.resource_id)}</div></td>
                          <td className="text-2">{a.owner_name}</td>
                          <td className="num nowrap">{fmtQty(a.quantity_allocated)} {a.unit_of_measure}</td>
                          <td><Badge value={a.allocation_status}>{ALLOCATION_STATUS_LABELS[a.allocation_status] || a.allocation_status}</Badge></td>
                          <td className="cell-sub" style={{ marginTop: 0 }}>
                            matched {fmtTime(a.matched_at)}
                            {a.dispatched_at && <div>dispatched {fmtTime(a.dispatched_at)}</div>}
                            {a.confirmed_at && <div>confirmed {fmtTime(a.confirmed_at)}</div>}
                            {a.distance_km != null && <div>{fmtQty(a.distance_km)} km away</div>}
                          </td>
                          <td className="actions">
                            <div className="btn-group" style={{ justifyContent: 'flex-end' }}>
                              {data.can_manage && (ALLOCATION_ACTIONS[a.allocation_status] || []).map(act => (
                                <button key={act.to} type="button"
                                        className={`btn btn-sm ${act.primary ? '' : act.danger ? 'btn-danger' : 'btn-secondary'}`}
                                        disabled={!!busy} onClick={() => doTransition(a, act.to)}>
                                  {busy === `tr-${a.allocation_id}-${act.to}` ? <Loader2 size={12} className="spin" /> : act.to === 'confirmed' ? <CheckCircle2 size={12} /> : act.to === 'dispatched' ? <Send size={12} /> : null}
                                  {act.label}
                                </button>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                      {data.reservations.map(r => (
                        <tr key={r.reservation_id} className={r.status === 'active' ? undefined : 'row-muted'}>
                          <td><span className="tag"><Lock size={11} style={{ marginRight: 4 }} />Reservation</span></td>
                          <td><div>{r.resource_subtype || r.resource_type}</div><div className="cell-sub mono">{short(r.resource_id)}</div></td>
                          <td className="text-2">{r.owner_name}</td>
                          <td className="num nowrap">{fmtQty(r.quantity)} {r.unit_of_measure}</td>
                          <td>
                            <Badge value={r.lease_active ? 'active' : r.status === 'active' ? 'expired' : r.status}>
                              {r.lease_active ? 'active lease' : r.status === 'active' ? 'lease lapsed' : r.status}
                            </Badge>
                          </td>
                          <td className="cell-sub" style={{ marginTop: 0 }}>
                            leased {fmtTime(r.created_at)}
                            <div>lease until {fmtTime(r.lease_expires_at)}</div>
                            {r.allocation_id && <div><ArrowRight size={11} /> allocation {r.allocation_id.substring(0, 8)}</div>}
                            <ScoreDetails components={r.score_components} score={r.final_score} />
                          </td>
                          <td className="actions">
                            {data.can_manage && r.lease_active && (
                              <div className="btn-group" style={{ justifyContent: 'flex-end' }}>
                                <button type="button" className="btn btn-sm" disabled={!!busy} onClick={() => doAllocate(r)}>
                                  {busy === `alloc-${r.reservation_id}` ? <Loader2 size={12} className="spin" /> : <CheckCircle2 size={12} />} Allocate
                                </button>
                                <button type="button" className="btn btn-secondary btn-sm" disabled={!!busy} onClick={() => doRelease(r)}>
                                  {busy === `rel-${r.reservation_id}` ? <Loader2 size={12} className="spin" /> : null} Release
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div>
              <div className="tracking-section-title"><Clock size={13} /> Details</div>
              <KeyValue items={[
                ['Requested', fmtTime(req.requested_at)],
                ['Needed by', fmtTime(req.needed_by)],
                ['Last change', fmtTime(data.last_change_at)],
                ['Record updated', fmtTime(req.updated_at)],
                ['Zone', req.zone_name],
                ['Urgency', <span key="u" className={`urgency urgency-${req.urgency_level}`}>{req.urgency_level}</span>],
                req.description ? ['Description', req.description] : null,
              ]} />

              <div className="tracking-section-title"><History size={13} /> Timeline</div>
              <ol className="timeline">
                {data.timeline.map((e, i) => (
                  <li key={`${e.at}-${i}`} className={`kind-${e.kind}`}>
                    <time dateTime={e.at}>{fmtTime(e.at)}</time>
                    <div>{e.label}</div>
                    {e.detail && <div className="tl-detail">{e.detail}</div>}
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
