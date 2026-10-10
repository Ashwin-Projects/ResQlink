import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { AlertTriangle, Zap, CheckCircle2, ArrowRight, Loader2, RefreshCw, Database, History, Layers, SlidersHorizontal, FlaskConical, Users } from 'lucide-react';
import { RESOURCE_TYPE_LABELS, STATUS_LABELS, label } from './resourceLabels';
import { PageHeader, Panel, Badge, LoadingState, EmptyState, ErrorState } from './ui';
import { fmtQty, fmtTime, short } from './format';

// Resource Change -> Incremental Re-matching (technical demonstration).
// Applies a REAL change to a resource (PATCH /api/v1/resources/{id}); the backend
// commits it with an event_outbox row in one transaction, then processes that
// event through the incremental re-matching path. Everything shown below comes
// from that API response or from event_outbox.processing_result — nothing here
// is simulated or estimated.

const CHANGES = [
  { key: 'unavailable', label: 'Mark unavailable (leaves service)', body: () => ({ status: 'unavailable' }) },
  { key: 'maintenance', label: 'Send to maintenance (leaves service)', body: () => ({ status: 'maintenance' }) },
  { key: 'available', label: 'Return to service (available)', body: () => ({ status: 'available' }) },
  { key: 'stock', label: 'Set total stock to…', body: (v) => ({ quantity_total: Number(v.qty) }) },
  { key: 'move', label: 'Move to another zone…', body: (v) => ({ current_zone_id: v.zone }) },
];

function StateCard({ title, state, zoneName, tone }) {
  if (!state) return null;
  return (
    <div className="metric" style={tone ? { borderColor: tone } : undefined}>
      <div className="metric-label">{title}</div>
      <div style={{ fontSize: 12.5, lineHeight: 1.8, marginTop: 4 }}>
        <div>status <Badge value={state.status}>{label(STATUS_LABELS, state.status)}</Badge></div>
        <div>available <strong className="num">{fmtQty(state.quantity_available)}</strong> / {fmtQty(state.quantity_total)}</div>
        <div className="text-2">zone {zoneName(state.current_zone_id)}</div>
      </div>
    </div>
  );
}

function FlowNode({ kicker, title, value, state }) {
  return (
    <li className={`pipeline-node ${state ? `is-${state}` : ''}`}>
      <div className="pipeline-kicker">{kicker}</div>
      <div className="pipeline-title">{title}</div>
      {value != null && <div className="pipeline-value">{value}</div>}
    </li>
  );
}

export default function HazardDemoView() {
  const [resources, setResources] = useState([]);
  const [zones, setZones] = useState([]);
  const [loadState, setLoadState] = useState('loading');
  const [loadError, setLoadError] = useState(null);
  const [resourceId, setResourceId] = useState('');
  const [changeKey, setChangeKey] = useState('unavailable');
  const [qty, setQty] = useState('');
  const [zone, setZone] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [runs, setRuns] = useState(null);

  const load = useCallback(async () => {
    try {
      const [res, opts] = await Promise.all([api.listResourcesLive({ limit: 500 }), api.getResourceFormOptions()]);
      setResources(res); setZones(opts.zones || []); setLoadError(null); setLoadState('ready');
    } catch (err) {
      setLoadError(err.message); setLoadState('error');
    }
    try { setRuns(await api.getRematchRuns(10)); } catch (err) { setRuns({ error: err.message }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const zoneName = useCallback((id) => zones.find(z => z.zone_id === id)?.zone_name || short(id), [zones]);
  const selected = useMemo(() => resources.find(r => r.resource_id === resourceId), [resources, resourceId]);

  const apply = async () => {
    if (!selected || busy) return;
    const change = CHANGES.find(c => c.key === changeKey);
    if (changeKey === 'stock' && !(String(qty).trim() !== '' && Number(qty) >= 0)) { setError('Enter the new total stock (≥ 0).'); return; }
    if (changeKey === 'move' && !zone) { setError('Select the destination zone.'); return; }
    setBusy(true); setError(null); setResult(null);
    try {
      const out = await api.updateResource(selected.resource_id, change.body({ qty, zone }));
      setResult(out);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      await load();
    }
  };

  const rm = result?.rematch;
  const processed = rm?.status === 'processed' || rm?.status === 'already_processed';
  const revokedN = result?.revoked_leases?.length || 0;

  return (
    <div>
      <PageHeader
        eyebrow="Technical demonstration"
        title="Hazard Simulator"
        subtitle="Apply a real change to a resource and watch the database innovation work: the change, lease revocation and an outbox event commit in one transaction; only the requests that depend on the affected pool(s) are re-matched."
        actions={(
          <>
            <Badge value="tone-violet" dot={false}><FlaskConical size={12} /> Real database execution</Badge>
            <button type="button" className="btn btn-secondary" onClick={load}><RefreshCw size={14} /> Refresh</button>
          </>
        )}
      />

      {/* The flow, lit up with the values of the last run */}
      <ol className="pipeline" aria-label="Incremental re-matching flow" style={{ marginBottom: 16 }}>
        <FlowNode kicker="Before" title={selected ? (selected.resource_subtype || label(RESOURCE_TYPE_LABELS, selected.resource_type)) : 'Pick a resource'}
                  value={selected ? `${fmtQty(selected.quantity_available)}/${fmtQty(selected.quantity_total)} · ${selected.status}` : '—'} state={selected ? 'done' : 'active'} />
        <FlowNode kicker="Change" title={CHANGES.find(c => c.key === changeKey)?.label.replace(/ \(.*\)|…/g, '')}
                  value={result ? `${revokedN} lease(s) revoked` : 'same transaction'} state={result ? 'done' : selected ? 'active' : undefined} />
        <FlowNode kicker="Outbox event" title={result ? `resource_updated · ${short(result.event_outbox_id)}` : 'event_outbox'}
                  value={rm ? rm.status : '—'} state={rm ? (processed ? 'done' : 'active') : undefined} />
        <FlowNode kicker="Affected pools" title={processed ? `${rm.affected_pools.length} pool(s)` : 'zone × type × mobility'}
                  value={processed ? `${rm.dependency_rows_examined} dependency rows read` : 'request_pool_dependency'} state={processed ? 'done' : undefined} />
        <FlowNode kicker="Dependent requests" title={processed ? `${rm.requests_evaluated} re-matched` : 'only dependents'}
                  value={processed ? `of ${rm.open_requests_in_database} open in DB` : '—'} state={processed ? 'key' : undefined} />
        <FlowNode kicker="Result" title={processed ? `${rm.leases_created} new · ${rm.leases_revoked} revoked` : '—'}
                  value={processed ? `${rm.elapsed_ms} ms measured` : '—'} state={processed ? 'done' : undefined} />
      </ol>

      <div className="grid-side-main">
        <Panel title="1. Choose a resource and a change" icon={SlidersHorizontal}>
          {loadState === 'loading' && <LoadingState compact label="Loading resources…" />}
          {loadState === 'error' && <ErrorState compact title="Unable to load resources" message={loadError} onRetry={load} />}
          <div className="form-group">
            <label className="form-label" htmlFor="sim_resource">Resource</label>
            <select id="sim_resource" className="form-select" value={resourceId} onChange={e => { setResourceId(e.target.value); setResult(null); }}>
              <option value="">Select a resource…</option>
              {resources.map(r => (
                <option key={r.resource_id} value={r.resource_id}>
                  {label(RESOURCE_TYPE_LABELS, r.resource_type)} · {r.resource_subtype || short(r.resource_id)} · {r.zone_name} · {fmtQty(r.quantity_available)}/{fmtQty(r.quantity_total)} · {r.status}
                </option>
              ))}
            </select>
            {selected && (
              <div className="field-hint">
                in use {fmtQty(selected.quantity_in_use)} (leased + allocated + consumed) · owner {selected.owner_name}
              </div>
            )}
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="sim_change">Change</label>
            <select id="sim_change" className="form-select" value={changeKey} onChange={e => setChangeKey(e.target.value)}>
              {CHANGES.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </div>
          {changeKey === 'stock' && (
            <div className="form-group">
              <label className="form-label" htmlFor="sim_qty">New total stock</label>
              <input id="sim_qty" className="form-input" type="number" min="0" step="0.01" value={qty} onChange={e => setQty(e.target.value)} />
            </div>
          )}
          {changeKey === 'move' && (
            <div className="form-group">
              <label className="form-label" htmlFor="sim_zone">Destination zone</label>
              <select id="sim_zone" className="form-select" value={zone} onChange={e => setZone(e.target.value)}>
                <option value="">Select zone…</option>
                {zones.filter(z => z.zone_id !== selected?.current_zone_id).map(z => <option key={z.zone_id} value={z.zone_id}>{z.zone_name}</option>)}
              </select>
            </div>
          )}
          {error && <div className="alert alert-error" role="alert"><AlertTriangle size={16} /><div>{error}</div></div>}
          <button className="btn btn-lg btn-block" onClick={apply} disabled={busy || !selected}>
            {busy ? <><Loader2 size={16} className="spin" /> Applying change & re-matching…</> : <><Zap size={16} /> Apply change → outbox → incremental re-match</>}
          </button>
          <div className="field-hint" style={{ marginTop: 10 }}>
            Uses <code>PATCH /api/v1/resources/{'{id}'}</code> — the same path as the Resources page. This changes real data.
          </div>
        </Panel>

        <Panel title="2. What actually happened" icon={Database} aria-live="polite">
          {!result ? (
            <EmptyState title="No change applied yet"
                        message="Apply a change to see the committed resource state, the outbox event and the incremental re-match outcome." />
          ) : (
            <div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'stretch', marginBottom: 12 }}>
                <StateCard title="Before" state={result.before} zoneName={zoneName} />
                <div style={{ display: 'flex', alignItems: 'center', color: 'var(--text-3)' }}><ArrowRight size={18} /></div>
                <StateCard title="After" state={result.after} zoneName={zoneName} tone="rgba(76,154,255,0.45)" />
              </div>
              <div className="cell-sub" style={{ marginBottom: 12, fontSize: 12.5 }}>
                Leases revoked in the same transaction: <strong style={{ color: 'var(--text)' }}>{revokedN}</strong>
                {revokedN > 0 && ' — '}
                {(result.revoked_leases || []).map((v, i) => (
                  <span key={v.reservation_id}>{i > 0 && ', '}{fmtQty(v.quantity)} from request <code>{short(v.request_id)}</code></span>
                ))}
              </div>

              <div className={`alert ${processed ? 'alert-success' : rm?.status === 'failed' ? 'alert-error' : 'alert-info'}`}>
                {processed ? <CheckCircle2 size={16} /> : <Database size={16} />}
                <div>
                  Outbox event <code>{short(result.event_outbox_id)}</code> — {rm?.status}
                  {rm?.status === 'skipped' && `: ${rm.reason}`}
                  {rm?.status === 'failed' && `: ${rm.error}`}
                  {rm?.status === 'claimed_by_worker' && ': the background worker is processing this event; its outcome will appear under Recent re-match runs'}
                  {rm?.processed_at && <> · processed {fmtTime(rm.processed_at)}</>}
                </div>
              </div>

              {processed && (
                <>
                  <div className="metric-row" style={{ marginBottom: 12 }}>
                    <div className="metric is-key">
                      <div className="metric-label">Requests re-matched (dependents)</div>
                      <div className="metric-value" data-testid="requests-evaluated">{rm.requests_evaluated}</div>
                      <div className="metric-hint">{rm.affected_request_ids.length} affected · {rm.dependency_rows_examined} dependency rows read</div>
                    </div>
                    <div className="metric">
                      <div className="metric-label">Open requests in the database</div>
                      <div className="metric-value" data-testid="open-requests">{rm.open_requests_in_database}</div>
                      <div className="metric-hint">not re-matched unless they depend on an affected pool</div>
                    </div>
                  </div>
                  <div className="cell-sub" style={{ marginBottom: 6, fontSize: 12.5 }}>
                    {rm.leases_created} new lease(s) · {rm.leases_revoked} revoked · {rm.matches_made} match(es) · re-match ran in <strong style={{ color: 'var(--text)' }}>{rm.elapsed_ms} ms</strong> (measured)
                  </div>

                  <div className="tracking-section-title"><Layers size={13} /> Affected pools</div>
                  {rm.affected_pools.length === 0 ? <EmptyState compact message="No pool exists yet for this zone and resource type (no request depends on it)." /> : (
                    <ul className="chip-row" style={{ listStyle: 'none' }} aria-label="Affected pools">
                      {rm.affected_pools.map(p => (
                        <li key={p.pool_id} className="tag" style={{ height: 'auto', padding: '4px 8px' }}><code>{short(p.pool_id)}</code>&nbsp;· {zoneName(p.zone_id)} × {p.resource_type} × {p.mobility_class}</li>
                      ))}
                    </ul>
                  )}

                  <div className="tracking-section-title"><Users size={13} /> Affected requests</div>
                  {rm.affected_requests.length === 0 ? <EmptyState compact message="No request depends on the affected pool(s)." /> : (
                    <div className="table-container">
                      <table className="data-table table-compact" aria-label="Affected requests">
                        <thead><tr><th>Request</th><th>Why</th><th>Leased: before → after revocation → after re-match</th><th className="right">Still to cover</th><th>New leases</th></tr></thead>
                        <tbody>
                          {rm.affected_requests.map(x => (
                            <tr key={x.request_id}>
                              <td className="cell-id" title={x.request_id}>{short(x.request_id)}<div className="cell-sub" style={{ fontFamily: 'var(--font)' }}>{x.after_rematch?.status}</div></td>
                              <td><div className="chip-row">{x.reasons.map(r => <span key={r} className="tag">{r.replace('_', ' ')}</span>)}</div></td>
                              <td className="num">{fmtQty(x.before_change?.quantity_leased)} → {fmtQty(x.before_rematch?.quantity_leased)} → <strong>{fmtQty(x.after_rematch?.quantity_leased)}</strong></td>
                              <td className="right num">{fmtQty(x.after_rematch?.quantity_to_cover)}</td>
                              <td className="cell-sub" style={{ marginTop: 0 }}>
                                {x.leases_created.length === 0 ? '—' : x.leases_created.map(l => (
                                  <div key={l.reservation_id}>{fmtQty(l.quantity)} from <code>{short(l.resource_id)}</code></div>
                                ))}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </Panel>
      </div>

      <div style={{ marginTop: 16 }}>
        <Panel flush title="Recent re-match runs" icon={History} subtitle={<>Stored outcomes from <code>event_outbox.processing_result</code></>}
               actions={<button type="button" className="btn btn-secondary btn-sm" onClick={load}><RefreshCw size={13} /> Refresh</button>}>
          {runs === null && <LoadingState compact label="Loading runs…" />}
          {runs?.error && <ErrorState compact title="Unable to load re-match runs" message={runs.error} />}
          {Array.isArray(runs) && runs.length === 0 && <EmptyState compact title="No processed re-match events yet" />}
          {Array.isArray(runs) && runs.length > 0 && (
            <div className="table-container">
              <table className="data-table" aria-label="Recent re-match runs">
                <thead><tr><th>Processed</th><th>Event</th><th>Outcome</th><th className="right">Pools</th><th className="right">Requests re-matched</th><th className="right">Leases created / revoked</th><th className="right">Time</th></tr></thead>
                <tbody>
                  {runs.map(r => {
                    const p = r.processing_result || {};
                    return (
                      <tr key={r.event_id}>
                        <td className="nowrap">{fmtTime(r.processed_at)}</td>
                        <td>{r.event_type}<div className="cell-sub mono">{short(r.event_id)}</div></td>
                        <td><Badge value={p.status === 'processed' ? 'processed' : p.status === 'failed' ? 'failed' : 'skipped'}>{p.status}</Badge></td>
                        <td className="right num">{p.affected_pools?.length ?? 0}</td>
                        <td className="right num">{p.requests_evaluated ?? 0}{p.open_requests_in_database != null && <span className="text-3"> of {p.open_requests_in_database} open</span>}</td>
                        <td className="right num">{p.leases_created ?? 0} / {p.leases_revoked ?? 0}</td>
                        <td className="right num nowrap">{p.elapsed_ms != null ? `${p.elapsed_ms} ms` : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
