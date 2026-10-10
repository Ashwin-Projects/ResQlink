import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { Field } from './CreateRequestForm';
import { RESOURCE_TYPE_LABELS, MOBILITY_LABELS, STATUS_LABELS, label, quantityError, coordinateErrors } from './resourceLabels';
import { Box, Loader2, AlertTriangle, CheckCircle2, X, History, Database, MapPin, GitMerge } from 'lucide-react';
import { Badge, LoadingState } from './ui';
import { short } from './format';

// Structured view of the incremental re-match outcome returned by PATCH
// /api/v1/resources/{id} (also stored in event_outbox.processing_result).
function RematchResult({ rm, revoked }) {
  if (!rm) return null;
  return (
    <div className="subtle-box" data-testid="rematch-result" style={{ marginTop: 12 }}>
      <div className="chip-row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <span className="card-title" style={{ fontSize: 13 }}><GitMerge size={14} className="card-title-icon" /> Incremental re-matching</span>
        <Badge value={rm.status === 'processed' ? 'processed' : rm.status === 'failed' ? 'failed' : 'skipped'}>{rm.status}</Badge>
      </div>
      {rm.status === 'processed' ? (
        <>
          <div className="metric-row">
            <div className="metric is-key"><div className="metric-label">Requests re-evaluated</div><div className="metric-value">{rm.requests_evaluated}</div><div className="metric-hint">dependents of affected pools</div></div>
            <div className="metric"><div className="metric-label">Leases created</div><div className="metric-value">{rm.leases_created}</div></div>
            <div className="metric"><div className="metric-label">Leases revoked</div><div className="metric-value">{rm.leases_revoked}</div></div>
            <div className="metric"><div className="metric-label">Re-match time</div><div className="metric-value">{rm.elapsed_ms}<span className="text-3" style={{ fontSize: 13 }}> ms</span></div><div className="metric-hint">measured</div></div>
          </div>
          <div className="cell-sub" style={{ marginTop: 10 }}>
            {(rm.affected_pools || []).length} affected pool(s){rm.open_requests_in_database != null && <> · {rm.open_requests_in_database} open requests in the database were not rescanned</>}
            {(rm.affected_request_ids || []).length > 0 && <> · requests {(rm.affected_request_ids || []).map(id => short(id)).join(', ')}</>}
            {(revoked || []).length > 0 && <> · {revoked.length} lease(s) revoked in the same transaction</>}
          </div>
        </>
      ) : (
        <div className="cell-sub">{rm.status === 'skipped' ? `Skipped: ${rm.reason}` : `Failed: ${rm.error} — the event stays queued for the worker.`}</div>
      )}
    </div>
  );
}

const fmtTime = (v) => (v ? new Date(v).toLocaleString() : '—');
const fmtQty = (v) => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }));

function formFrom(r) {
  return {
    quantity_total: String(r.quantity_total),
    status: r.status,
    current_zone_id: r.current_zone_id,
    latitude: '', longitude: '',
    mobility_class: r.mobility_class || '',
    resource_subtype: r.resource_subtype || '',
    condition_notes: r.condition_notes || '',
  };
}

// Only fields that actually changed are sent (PATCH semantics).
export function buildChanges(form, r) {
  const c = {};
  if (Number(form.quantity_total) !== Number(r.quantity_total)) c.quantity_total = Number(form.quantity_total);
  if (form.status !== r.status) c.status = form.status;
  if (form.current_zone_id !== r.current_zone_id) c.current_zone_id = form.current_zone_id;
  if (String(form.latitude).trim() !== '') { c.latitude = Number(form.latitude); c.longitude = Number(form.longitude); }
  if ((form.mobility_class || null) !== (r.mobility_class || null)) c.mobility_class = form.mobility_class || null;
  if (form.resource_subtype.trim() !== (r.resource_subtype || '')) c.resource_subtype = form.resource_subtype.trim() || null;
  if (form.condition_notes.trim() !== (r.condition_notes || '')) c.condition_notes = form.condition_notes.trim() || null;
  return c;
}

export default function ResourceEditPanel({ resourceId, options, onClose, onSaved }) {
  const [detail, setDetail] = useState(null);
  const [state, setState] = useState('loading');
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [lastResult, setLastResult] = useState(null);

  // resetForm: only on first load and after a successful save, so a late or
  // duplicate load (e.g. React StrictMode) never overwrites what the user typed.
  const load = useCallback(async ({ resetForm = false } = {}) => {
    try {
      const d = await api.getResourceDetail(resourceId);
      setDetail(d);
      setForm(f => (resetForm || f === null ? formFrom(d.resource) : f));
      setState('ready');
    } catch (err) {
      setMsg({ kind: 'error', text: err.status === 404 ? 'Resource not found or not visible to your role.' : err.message });
      setState('error');
    }
  }, [resourceId]);

  useEffect(() => { setState('loading'); setMsg(null); load(); }, [load]);

  const set = (k) => (e) => {
    const v = e.target.value;
    setForm(f => ({ ...f, [k]: v }));
    if (errors[k]) setErrors(x => { const n = { ...x }; delete n[k]; return n; });
  };
  const editable = detail?.can_edit;
  const fp = (id) => ({ id: `edit_${id}`, name: id, value: form[id], onChange: set(id), disabled: saving || !editable,
    'aria-invalid': errors[id] ? 'true' : undefined });

  const save = async (e) => {
    e.preventDefault();
    const r = detail.resource;
    const v = {};
    const qe = quantityError(form.quantity_total);
    if (qe) v.quantity_total = qe;
    else if (Number(form.quantity_total) < r.quantity_in_use - detail.quantity_leased) {
      v.quantity_total = `At least ${fmtQty(r.quantity_in_use - detail.quantity_leased)} (allocated or consumed).`;
    }
    Object.assign(v, coordinateErrors(form.latitude, form.longitude));
    if (form.resource_subtype.trim().length > 100) v.resource_subtype = 'At most 100 characters.';
    if (form.condition_notes.trim().length > 1000) v.condition_notes = 'At most 1000 characters.';
    setErrors(v);
    if (Object.keys(v).length) { setMsg({ kind: 'error', text: 'Please correct the highlighted fields.' }); return; }
    const changes = buildChanges(form, r);
    if (!Object.keys(changes).length) { setMsg({ kind: 'error', text: 'Nothing changed.' }); return; }
    setSaving(true); setMsg(null); setLastResult(null);
    try {
      const result = await api.updateResource(resourceId, changes);
      setLastResult(result);
      await load({ resetForm: true });  // re-read values, ledger and history from the database
      onSaved?.(result);
      const s = result.resource.status !== changes.status && changes.status
        ? ` Status stored as '${result.resource.status}' (database rule).` : '';
      const rm = result.rematch;
      const rmText = rm?.status === 'processed'
        ? ` Incremental re-match: ${rm.requests_evaluated} dependent request(s) re-evaluated, ${rm.leases_created} new lease(s), ${rm.leases_revoked} revoked (${rm.elapsed_ms} ms).`
        : rm?.status === 'failed' ? ` Re-match failed (${rm.error}); the event stays queued for the worker.` : '';
      setMsg({ kind: 'success', text: `Saved: ${Object.keys(result.changes || changes).join(', ')}.${s}${rmText}` });
    } catch (err) {
      setErrors(err.fieldErrors || {});
      setMsg({ kind: 'error', text: err.message });
      if (err.kind !== 'network') await load();   // show the current database state, keep the user's input
    } finally {
      setSaving(false);
    }
  };

  const r = detail?.resource;
  const statusChoices = r ? Array.from(new Set([r.status, ...options.operator_statuses])) : [];

  return (
    <section className="card" aria-label={editable ? 'Update Resource' : 'Resource Details'}>
      <div className="card-header">
        <div className="card-heading">
          <h2 className="card-title" id="edit-resource-title"><Box size={16} className="card-title-icon" /> {editable ? 'Update Resource' : 'Resource Details'}</h2>
          <div className="card-subtitle mono">{resourceId}</div>
        </div>
        <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Close resource panel"><X size={14} /></button>
      </div>

      {state === 'loading' && <LoadingState label="Loading from the database…" />}
      {msg && (
        <div className={`alert alert-${msg.kind === 'success' ? 'success' : 'error'}`} role={msg.kind === 'error' ? 'alert' : 'status'}>
          {msg.kind === 'success' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          <div className="alert-body">{msg.text}</div>
        </div>
      )}
      {lastResult && <RematchResult rm={lastResult.rematch} revoked={lastResult.revoked_leases} />}

      {state === 'ready' && r && (
        <>
          <div className="chip-row" style={{ margin: '14px 0 12px' }}>
            <span className="cell-main">{label(RESOURCE_TYPE_LABELS, r.resource_type)}{r.resource_subtype ? ` · ${r.resource_subtype}` : ''}</span>
            <Badge value={r.status}>{label(STATUS_LABELS, r.status)}</Badge>
            <span className="text-3">{r.owner_name} · {r.zone_name}</span>
          </div>
          <div className="metric-row" style={{ marginBottom: 14 }}>
            <div className="metric"><div className="metric-label">Available</div><div className="metric-value" style={{ color: 'var(--green)' }}>{fmtQty(r.quantity_available)}</div><div className="metric-hint">of {fmtQty(r.quantity_total)} {r.unit_of_measure}</div></div>
            <div className="metric"><div className="metric-label">In use</div><div className="metric-value">{fmtQty(r.quantity_in_use)}</div><div className="metric-hint">in use {fmtQty(r.quantity_in_use)} (leased {fmtQty(detail.quantity_leased)}, allocated {fmtQty(detail.quantity_allocated)})</div></div>
            <div className="metric"><div className="metric-label">Last verified</div><div className="metric-value" style={{ fontSize: 13, paddingTop: 6 }}>{fmtTime(r.last_verified_at)}</div></div>
          </div>
          {!editable && (
            <div className="field-hint" style={{ marginBottom: 10 }}>
              Read-only: only a coordinator or this resource's owner can update it (you are <code>{options.current_role}</code>).
            </div>
          )}

          <form onSubmit={save} noValidate aria-busy={saving}>
            <div className="form-grid-2">
              <Field id="edit_quantity_total" labelText="Total Quantity" error={errors.quantity_total}
                     hint={`Changes move available stock by the same amount. Below ${fmtQty(r.quantity_in_use)} in use, active leases are revoked and re-matched; minimum ${fmtQty(r.quantity_in_use - detail.quantity_leased)} (allocated or consumed).`}>
                <input className="form-input" type="number" min="0" step="0.01" {...fp('quantity_total')} />
              </Field>
              <Field id="edit_status" labelText="Availability" error={errors.status}
                     hint="'Depleted' is set by the database when no stock is free.">
                <select className="form-select" {...fp('status')}>
                  {statusChoices.map(s => (
                    <option key={s} value={s} disabled={!options.operator_statuses.includes(s)}>{label(STATUS_LABELS, s)}</option>
                  ))}
                </select>
              </Field>
              <Field id="edit_mobility_class" labelText="Mobility Class" error={errors.mobility_class}>
                <select className="form-select" {...fp('mobility_class')}>
                  <option value="">Not specified</option>
                  {options.mobility_classes.map(m => <option key={m} value={m}>{label(MOBILITY_LABELS, m)}</option>)}
                </select>
              </Field>
              <Field id="edit_current_zone_id" labelText="Zone" error={errors.current_zone_id}
                     hint="Changing the zone moves the resource to the zone point unless coordinates are given.">
                <select className="form-select" {...fp('current_zone_id')}>
                  {options.zones.map(z => <option key={z.zone_id} value={z.zone_id}>{z.zone_name} ({z.zone_type})</option>)}
                </select>
              </Field>
              <Field id="edit_latitude" labelText="New Latitude (optional)" error={errors.latitude}
                     hint={r.latitude != null ? `Current ${Number(r.latitude).toFixed(4)}` : undefined}>
                <input className="form-input" type="number" step="any" {...fp('latitude')} />
              </Field>
              <Field id="edit_longitude" labelText="New Longitude (optional)" error={errors.longitude}
                     hint={r.longitude != null ? `Current ${Number(r.longitude).toFixed(4)}` : undefined}>
                <input className="form-input" type="number" step="any" {...fp('longitude')} />
              </Field>
              <Field id="edit_resource_subtype" labelText="Subtype / Description" error={errors.resource_subtype}>
                <input className="form-input" maxLength={100} {...fp('resource_subtype')} />
              </Field>
              <div className="span-2">
                <Field id="edit_condition_notes" labelText="Condition Notes" error={errors.condition_notes}>
                  <input className="form-input" maxLength={1000} {...fp('condition_notes')} />
                </Field>
              </div>
            </div>
            {editable && (
              <div className="form-footer">
                <span className="form-footer-note">Only changed fields are sent. Stock / availability / zone changes re-match dependent requests.</span>
                <div className="btn-group">
                  <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>Close</button>
                  <button type="submit" className="btn" disabled={saving}>
                    {saving ? <><Loader2 size={15} className="spin" /> Saving…</> : <><CheckCircle2 size={15} /> Save Changes</>}
                  </button>
                </div>
              </div>
            )}
          </form>

          <div className="grid-2" style={{ marginTop: 6 }}>
            <div>
              <div className="tracking-section-title"><History size={13} /> Change history (audit log)</div>
              <ol className="timeline" aria-label="Resource history">
                {detail.history.map(h => (
                  <li key={h.log_id} className={`kind-${h.action === 'status_changed' ? 'request_status' : h.action === 'quantity_updated' ? 'allocation' : 'request_created'}`}>
                    <time dateTime={h.performed_at}>{fmtTime(h.performed_at)}</time>
                    <div>{h.remarks || h.action}</div>
                    {h.action !== 'created' && h.new_value && (
                      <div className="tl-detail">
                        {Object.keys(h.new_value).filter(k => !['last_verified_at', 'location_changed'].includes(k)).map(k => (
                          <span key={k} style={{ marginRight: '8px' }}>{k}: {JSON.stringify(h.old_value?.[k])} → {JSON.stringify(h.new_value[k])}</span>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </div>
            <div>
              <div className="tracking-section-title"><Database size={13} /> Stock ledger</div>
              <dl className="kv-list" aria-label="Resource ledger">
                {detail.ledger.map(l => (
                  <React.Fragment key={l.id}>
                    <dt>{fmtTime(l.created_at)}</dt>
                    <dd>{l.delta_qty > 0 ? '+' : ''}{fmtQty(l.delta_qty)} · {l.reason}</dd>
                  </React.Fragment>
                ))}
              </dl>
              <div className="tracking-section-title"><MapPin size={13} /> Location history</div>
              <dl className="kv-list">
                {detail.location_history.map(l => (
                  <React.Fragment key={l.id}>
                    <dt>{fmtTime(l.recorded_at)}</dt>
                    <dd>{l.latitude != null ? `${Number(l.latitude).toFixed(4)}, ${Number(l.longitude).toFixed(4)}` : '—'} · {l.source}</dd>
                  </React.Fragment>
                ))}
              </dl>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
