import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { GitMerge, Search, Zap, Lock, Loader2, RefreshCw, Target, Scale } from 'lucide-react';
import RequestTrackingPanel from './RequestTrackingPanel';
import { PageHeader, Panel, Badge, LoadingState, ErrorState, EmptyState } from './ui';
import { fmtQty, fmtTime, short, STAGE_LABELS } from './format';
import { RESOURCE_TYPE_LABELS, label } from './resourceLabels';

// Matching workflow: Request → Candidate resources → Matching decision →
// Reservation (lease) → Allocation. Every value shown comes from the API:
//   GET  /api/v1/match/requests/{id}/candidates   (read-only scoring preview)
//   POST /api/v1/match/requests/{id}/match        (leases via FOR UPDATE SKIP LOCKED)
//   GET  /api/v1/requests/{id}/tracking           (reservations / allocations)
const OPEN_STAGES = ['pending', 'matching', 'partially_fulfilled'];

function ScoreBreakdown({ components, score, maxKm }) {
  const c = components || {};
  const proximity = c.distance_m != null && maxKm ? Math.max(0, 1 - (c.distance_m / 1000) / maxKm) : null;
  const rows = [
    ['Proximity', proximity, c.distance_m != null ? `${(c.distance_m / 1000).toFixed(2)} km` : null],
    ['Confidence', c.confidence, null],
    ['Accessibility', c.accessibility, null],
  ];
  return (
    <div className="score-break">
      {rows.map(([k, v, note]) => (
        <div className="score-row" key={k} title={note || undefined}>
          <span>{k}</span>
          <span className="bar"><span style={{ width: `${v == null ? 0 : Math.max(0, Math.min(1, Number(v))) * 100}%` }} /></span>
          <span className="val">{v == null ? '—' : Number(v).toFixed(2)}</span>
        </div>
      ))}
      <div className="score-row">
        <span>Urgency bonus</span><span />
        <span className="val">+{Number(c.urgency_bonus || 0).toFixed(2)}</span>
      </div>
      {score != null && <div className="cell-sub">final score <strong style={{ color: 'var(--text)' }}>{Number(score).toFixed(3)}</strong></div>}
    </div>
  );
}

function PipelineNode({ kicker, title, value, state }) {
  return (
    <li className={`pipeline-node ${state ? `is-${state}` : ''}`}>
      <div className="pipeline-kicker">{kicker}</div>
      <div className="pipeline-title">{title}</div>
      <div className="pipeline-value">{value}</div>
    </li>
  );
}

export default function MatchingDemoView({ selectedRequest: propRequest }) {
  const [requests, setRequests] = useState([]);
  const [listState, setListState] = useState('loading');
  const [listError, setListError] = useState(null);
  const [selectedReqId, setSelectedReqId] = useState(propRequest?.request_id || '');
  const [mode, setMode] = useState('incremental');
  const [candidates, setCandidates] = useState(null);       // null | {error} | response
  const [running, setRunning] = useState(false);
  const [matchResult, setMatchResult] = useState(null);     // { mode, at, proposed_reservations } | { error }
  const [panelKey, setPanelKey] = useState(0);

  const loadRequests = useCallback(async () => {
    setListState('loading');
    try {
      const data = await api.listEmergencyRequests({ limit: 200 });
      const open = data.filter(r => OPEN_STAGES.includes(r.tracking_stage || r.status));
      // A request handed over from the Requests page must stay selectable.
      const withProp = propRequest && !open.some(r => r.request_id === propRequest.request_id) ? [propRequest, ...open] : open;
      setRequests(withProp);
      setListState('ready');
      setListError(null);
      setSelectedReqId(id => id || withProp[0]?.request_id || '');
    } catch (err) {
      setListError(err.message);
      setListState('error');
    }
  }, [propRequest]);
  useEffect(() => { loadRequests(); }, [loadRequests]);

  const loadCandidates = useCallback(async (id) => {
    if (!id) return;
    setCandidates(null);
    try { setCandidates(await api.getMatchCandidates(id)); } catch (err) { setCandidates({ error: err.message }); }
  }, []);
  useEffect(() => { setMatchResult(null); loadCandidates(selectedReqId); }, [selectedReqId, loadCandidates]);

  const activeReq = useMemo(() => requests.find(r => r.request_id === selectedReqId), [requests, selectedReqId]);
  const candidateById = useMemo(() => Object.fromEntries((candidates?.candidates || []).map(c => [c.resource_id, c])), [candidates]);

  const run = async () => {
    if (!selectedReqId || running) return;
    setRunning(true);
    try {
      const result = await api.matchRequest(selectedReqId, mode);
      setMatchResult({ mode, at: new Date().toISOString(), proposed_reservations: result.proposed_reservations || [] });
    } catch (err) {
      setMatchResult({ error: err.message });
    } finally {
      setRunning(false);
      setPanelKey(k => k + 1);             // re-read reservations / allocations
      loadCandidates(selectedReqId);       // availability changed
    }
  };

  const proposals = matchResult?.proposed_reservations || [];
  const leasedQty = proposals.reduce((s, x) => s + Number(x.quantity || 0), 0);
  const nCand = candidates?.candidates?.length;

  return (
    <div>
      <PageHeader
        eyebrow="Operations"
        title="Matching"
        subtitle="Request → candidate resources → matching decision → reservation (lease) → allocation. Candidates come from spatial retrieval and scoring; leases are taken atomically with FOR UPDATE SKIP LOCKED."
        actions={(
          <button type="button" className="btn btn-secondary" onClick={loadRequests} disabled={listState === 'loading'}>
            <RefreshCw size={14} /> Refresh
          </button>
        )}
      />

      <ol className="pipeline" aria-label="Matching pipeline" style={{ marginBottom: 16 }}>
        <PipelineNode kicker="1 · Request" title={activeReq ? `${fmtQty(activeReq.quantity_requested)} × ${label(RESOURCE_TYPE_LABELS, activeReq.resource_type_needed)}` : 'Select a request'}
                      value={activeReq ? `${activeReq.zone_name || '—'} · ${activeReq.urgency_level}` : '—'} state={activeReq ? 'done' : 'active'} />
        <PipelineNode kicker="2 · Candidates" title={nCand == null ? 'Scoring…' : `${nCand} candidate${nCand === 1 ? '' : 's'}`}
                      value={candidates && !candidates.error ? `within ${candidates.max_distance_km} km · ${fmtQty(candidates.quantity_to_cover)} to cover` : '—'}
                      state={nCand ? 'done' : activeReq ? 'active' : undefined} />
        <PipelineNode kicker="3 · Decision" title={matchResult ? (matchResult.error ? 'Failed' : `${proposals.length} decision${proposals.length === 1 ? '' : 's'}`) : 'Not run yet'}
                      value={matchResult && !matchResult.error ? `mode ${matchResult.mode}` : 'matching_decision'}
                      state={matchResult && !matchResult.error ? 'done' : nCand ? 'active' : undefined} />
        <PipelineNode kicker="4 · Reservation" title={matchResult && !matchResult.error ? `${fmtQty(leasedQty)} leased` : '—'}
                      value="1 h lease · contention-safe" state={proposals.length ? 'done' : undefined} />
        <PipelineNode kicker="5 · Allocation" title="Allocate → dispatch → confirm" value="in the tracking panel below"
                      state={proposals.length ? 'active' : undefined} />
      </ol>

      <div className="grid-side-main">
        <Panel title="Request" icon={Target} subtitle="Open requests (pending, matching, partially fulfilled)">
          {listState === 'loading' && <LoadingState compact label="Loading open requests…" />}
          {listState === 'error' && <ErrorState compact title="Unable to load requests" message={listError} onRetry={loadRequests} />}
          {listState === 'ready' && requests.length === 0 && (
            <EmptyState compact title="No open requests" message="Every request is fulfilled, cancelled or expired." />
          )}
          {listState === 'ready' && requests.length > 0 && (
            <>
              <div className="form-group">
                <label className="form-label" htmlFor="match_request">Request to match</label>
                <select id="match_request" className="form-select" value={selectedReqId} onChange={e => setSelectedReqId(e.target.value)}>
                  {requests.map(r => (
                    <option key={r.request_id} value={r.request_id}>
                      [{r.urgency_level}] {label(RESOURCE_TYPE_LABELS, r.resource_type_needed)} × {fmtQty(r.quantity_requested)} · {r.zone_name || '—'} · {short(r.request_id)}
                    </option>
                  ))}
                </select>
              </div>

              {activeReq && (
                <div className="subtle-box request-card" style={{ marginBottom: 14 }}>
                  <div className="request-card-row"><span>Stage</span><Badge value={activeReq.tracking_stage || activeReq.status}>{STAGE_LABELS[activeReq.tracking_stage || activeReq.status] || activeReq.status}</Badge></div>
                  <div className="request-card-row"><span>Needs</span><strong>{label(RESOURCE_TYPE_LABELS, activeReq.resource_type_needed)}</strong></div>
                  <div className="request-card-row"><span>Requested / fulfilled</span><strong className="num">{fmtQty(activeReq.quantity_requested)} / {fmtQty(activeReq.quantity_fulfilled)}</strong></div>
                  <div className="request-card-row"><span>Still to cover</span><strong className="num">{candidates && !candidates.error ? fmtQty(candidates.quantity_to_cover) : '—'}</strong></div>
                  <div className="request-card-row"><span>Urgency</span><span className={`urgency urgency-${activeReq.urgency_level}`}>{activeReq.urgency_level}</span></div>
                  <div className="request-card-row"><span>Zone</span><strong>{activeReq.zone_name || '—'}</strong></div>
                  {activeReq.description && <div className="cell-sub">{activeReq.description}</div>}
                </div>
              )}

              <div className="form-group">
                <span className="form-label">Decision mode</span>
                <div className="segmented" role="group" aria-label="Decision mode">
                  <button type="button" aria-pressed={mode === 'incremental'} onClick={() => setMode('incremental')}>Incremental</button>
                  <button type="button" aria-pressed={mode === 'full_scan'} onClick={() => setMode('full_scan')}>Full scan (baseline)</button>
                </div>
                <div className="field-hint">Recorded on <code>matching_decision.mode</code> for each lease.</div>
              </div>

              <button type="button" className="btn btn-lg btn-block" onClick={run} disabled={running || !selectedReqId}>
                {running ? <><Loader2 size={16} className="spin" /> Running matching engine…</> : <><Zap size={16} /> Run matching engine</>}
              </button>
            </>
          )}
        </Panel>

        <Panel flush title="Candidate resources" icon={Search}
               subtitle={candidates && !candidates.error ? `Read-only preview — same retrieval and scoring as the engine, nothing reserved · within ${candidates.max_distance_km} km` : 'Read-only preview of the scoring'}
               actions={selectedReqId && <button type="button" className="btn btn-ghost btn-sm" onClick={() => loadCandidates(selectedReqId)}><RefreshCw size={13} /> Re-score</button>}>
          <div style={{ padding: '0 20px 14px' }}>
            <div className="formula" title="MatchingEngine.score_candidates">
              score = (1 − distance / max_distance) × confidence × accessibility + urgency_bonus
            </div>
          </div>
          {!selectedReqId && <EmptyState compact title="Select a request" />}
          {selectedReqId && !candidates && <LoadingState label="Scoring candidates…" />}
          {candidates?.error && <ErrorState compact title="Unable to score candidates" message={candidates.error} onRetry={() => loadCandidates(selectedReqId)} />}
          {candidates && !candidates.error && candidates.candidates.length === 0 && (
            <EmptyState title="No candidates in range"
                        message={`No available ${activeReq ? label(RESOURCE_TYPE_LABELS, activeReq.resource_type_needed).toLowerCase() : 'resources'} with free stock within ${candidates.max_distance_km} km.`} />
          )}
          {candidates && !candidates.error && candidates.candidates.length > 0 && (
            <div className="table-container">
              <table className="data-table" aria-label="Match candidates">
                <thead><tr><th>#</th><th>Resource</th><th className="right">Available</th><th className="right">Distance</th><th>Score breakdown</th><th className="right">Score</th></tr></thead>
                <tbody>
                  {candidates.candidates.map((c, i) => (
                    <tr key={c.resource_id}>
                      <td className="num">{i + 1}</td>
                      <td><div className="cell-main">{c.resource_subtype || label(RESOURCE_TYPE_LABELS, c.resource_type)}</div><div className="cell-sub mono">{short(c.resource_id)}</div></td>
                      <td className="right num nowrap">{fmtQty(c.quantity_available)} {c.unit_of_measure}</td>
                      <td className="right num nowrap">{Number(c.distance_km).toFixed(2)} km</td>
                      <td><ScoreBreakdown components={c.score_components} maxKm={candidates.max_distance_km} /></td>
                      <td className="right"><span className="score-total">{Number(c.score).toFixed(3)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <div style={{ marginTop: 16 }}>
        <Panel title="Matching decision → reservation" icon={Scale}
               subtitle="Leases created by the last run on this page (matching_decision + reservation rows, 1 h lease)">
          {!matchResult && <EmptyState compact title="No run yet" message='Use "Run matching engine" to lease the best candidates for the selected request.' />}
          {matchResult?.error && <ErrorState compact title="Matching failed" message={matchResult.error} />}
          {matchResult && !matchResult.error && proposals.length === 0 && (
            <EmptyState compact title="Matching ran — nothing leased" message="No candidate had free stock, or nothing was left to cover." />
          )}
          {proposals.length > 0 && (
            <>
              <div className="alert alert-success" role="status">
                <Lock size={16} />
                <div className="alert-body">
                  <div className="alert-title">Leased {fmtQty(leasedQty)} from {proposals.length} resource{proposals.length > 1 ? 's' : ''}</div>
                  <div>Mode <code>{matchResult.mode}</code> · run at {fmtTime(matchResult.at)} · rows locked with <code>FOR UPDATE SKIP LOCKED</code></div>
                </div>
              </div>
              <div className="grid-3">
                {proposals.map(p => {
                  const cand = candidateById[p.resource_id];
                  return (
                    <div className="decision-card" key={p.reservation_id}>
                      <div className="decision-head">
                        <div>
                          <div className="cell-main">{cand?.resource_subtype || (cand ? label(RESOURCE_TYPE_LABELS, cand.resource_type) : 'Resource')}</div>
                          <div className="cell-sub mono">{short(p.resource_id)} · lease {short(p.reservation_id)}</div>
                        </div>
                        <Badge value="active">leased {fmtQty(p.quantity)}</Badge>
                      </div>
                      {p.score_components
                        ? <ScoreBreakdown components={p.score_components} score={p.score} maxKm={candidates?.max_distance_km} />
                        : <div className="cell-sub">final score {Number(p.score).toFixed(3)}</div>}
                      {p.lease_expires_at && <div className="cell-sub">lease until {fmtTime(p.lease_expires_at)}</div>}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </Panel>
      </div>

      {selectedReqId && (
        <div style={{ marginTop: 16 }}>
          <div className="section-title"><GitMerge size={13} /> Reservation → allocation → dispatch → confirmation</div>
          <RequestTrackingPanel key={`${selectedReqId}-${panelKey}`} requestId={selectedReqId} hideMatchControls embedded />
        </div>
      )}
    </div>
  );
}
