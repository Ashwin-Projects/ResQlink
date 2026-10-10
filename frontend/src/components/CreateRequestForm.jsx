import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { PlusCircle, Send, Loader2, CheckCircle2, AlertTriangle, X } from 'lucide-react';
import { RESOURCE_TYPE_LABELS as RESOURCE_LABELS } from './resourceLabels';
import { URGENCY_LABELS } from './format';
import { LoadingState, ErrorState } from './ui';

// Display labels only — the allowed VALUES always come from the backend
// (/api/v1/requests/form-options), which mirrors the database CHECK constraints.
const MOBILITY_LABELS = {
  any: 'No special access requirement',
  land: 'Road access (land vehicles)',
  boat: 'Boat access only (flooded area)',
  amphibious: 'Amphibious access',
  air: 'Air access only',
};

const MAX_QUANTITY = 99999999.99; // NUMERIC(10,2)
const MAX_DESCRIPTION = 1000;

const label = (map, value) => map[value] || value;

function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `web-${crypto.randomUUID()}`;
  }
  // crypto.randomUUID is unavailable on non-secure origins (plain http on a LAN IP).
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

const EMPTY_FORM = {
  requester_id: '',
  resource_type_needed: '',
  quantity_requested: '',
  urgency_level: '',
  zone_id: '',
  mobility_requirement: 'any',
  needed_by: '',
  latitude: '',
  longitude: '',
  description: '',
};

export function validateRequestForm(form, options) {
  const errors = {};
  const requesterIds = new Set((options?.requesters || []).map(r => r.requester_id));
  const zoneIds = new Set((options?.zones || []).map(z => z.zone_id));

  if (!form.requester_id) errors.requester_id = 'Select the requester.';
  else if (!requesterIds.has(form.requester_id)) errors.requester_id = 'Select a valid requester.';

  if (!form.resource_type_needed) errors.resource_type_needed = 'Select the resource type needed.';
  else if (!(options?.resource_types || []).includes(form.resource_type_needed)) errors.resource_type_needed = 'Select a valid resource type.';

  const qtyText = String(form.quantity_requested).trim();
  const qty = Number(qtyText);
  if (!qtyText) errors.quantity_requested = 'Enter the quantity required.';
  else if (!Number.isFinite(qty) || qty <= 0) errors.quantity_requested = 'Quantity must be a number greater than 0.';
  else if (qty > MAX_QUANTITY) errors.quantity_requested = 'Quantity is too large.';
  else if (!/^\d+(\.\d{1,2})?$/.test(qtyText)) errors.quantity_requested = 'Use at most 2 decimal places.';

  if (!form.urgency_level) errors.urgency_level = 'Select the urgency level.';
  else if (!(options?.urgency_levels || []).includes(form.urgency_level)) errors.urgency_level = 'Select a valid urgency level.';

  if (!form.zone_id) errors.zone_id = 'Select the zone / location.';
  else if (!zoneIds.has(form.zone_id)) errors.zone_id = 'Select a valid zone.';

  if (!(options?.mobility_classes || []).includes(form.mobility_requirement)) {
    errors.mobility_requirement = 'Select a valid access requirement.';
  }

  if (form.needed_by) {
    const t = new Date(form.needed_by);
    if (Number.isNaN(t.getTime())) errors.needed_by = 'Enter a valid date and time.';
    else if (t.getTime() <= Date.now()) errors.needed_by = 'Needed-by time must be in the future.';
  }

  const hasLat = String(form.latitude).trim() !== '';
  const hasLng = String(form.longitude).trim() !== '';
  if (hasLat !== hasLng) {
    errors[hasLat ? 'longitude' : 'latitude'] = 'Enter both latitude and longitude, or leave both blank.';
  } else if (hasLat) {
    const lat = Number(form.latitude);
    const lng = Number(form.longitude);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90) errors.latitude = 'Latitude must be between -90 and 90.';
    if (!Number.isFinite(lng) || lng < -180 || lng > 180) errors.longitude = 'Longitude must be between -180 and 180.';
  }

  if (form.description.trim().length > MAX_DESCRIPTION) {
    errors.description = `Description must be at most ${MAX_DESCRIPTION} characters.`;
  }
  return errors;
}

export function buildRequestPayload(form, idempotencyKey) {
  const payload = {
    requester_id: form.requester_id,
    zone_id: form.zone_id,
    resource_type_needed: form.resource_type_needed,
    quantity_requested: Number(form.quantity_requested),
    urgency_level: form.urgency_level,
    mobility_requirement: form.mobility_requirement,
    description: form.description.trim() || null,
    idempotency_key: idempotencyKey,
    source_channel: 'web',
  };
  if (form.needed_by) payload.needed_by = new Date(form.needed_by).toISOString();
  if (String(form.latitude).trim() !== '') {
    payload.latitude = Number(form.latitude);
    payload.longitude = Number(form.longitude);
  }
  return payload;
}

function errorMessageFor(err) {
  switch (err?.kind) {
    case 'network': return err.message;
    case 'auth': return 'Authentication failed: your access token is invalid or expired.';
    case 'forbidden': return `Not permitted: ${err.message}`;
    case 'validation': return `The server rejected the request: ${err.message}`;
    case 'conflict': return err.message;
    case 'server': return `Server error (${err.status}): ${err.message}`;
    default: return err?.message || 'Unexpected error while submitting the request.';
  }
}

export function Field({ id, labelText, required, error, hint, children }) {
  return (
    <div className="form-group">
      <label className="form-label" htmlFor={id}>
        {labelText}{required && <span className="required-mark" aria-hidden="true">*</span>}
      </label>
      {children}
      {error ? <div className="field-error" id={`${id}-error`} role="alert">{error}</div>
             : hint ? <div className="field-hint">{hint}</div> : null}
    </div>
  );
}

export default function CreateRequestForm({ onCreated, onClose }) {
  const [options, setOptions] = useState(null);
  const [optionsState, setOptionsState] = useState('loading'); // loading | ready | error
  const [optionsError, setOptionsError] = useState(null);

  const [form, setForm] = useState(EMPTY_FORM);
  const [errors, setErrors] = useState({});
  const [submitState, setSubmitState] = useState('idle'); // idle | submitting | success | error
  const [submitError, setSubmitError] = useState(null);
  const [created, setCreated] = useState(null);
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);

  const loadOptions = useCallback(async () => {
    setOptionsState('loading');
    setOptionsError(null);
    try {
      const data = await api.getRequestFormOptions();
      setOptions(data);
      setOptionsState('ready');
      // A requester-role caller only sees itself (RLS): preselect it.
      if (data.requesters.length === 1) {
        setForm(f => ({ ...f, requester_id: f.requester_id || data.requesters[0].requester_id }));
      }
    } catch (err) {
      setOptionsError(errorMessageFor(err));
      setOptionsState('error');
    }
  }, []);

  useEffect(() => { loadOptions(); }, [loadOptions]);

  const selectedZone = useMemo(
    () => options?.zones.find(z => z.zone_id === form.zone_id),
    [options, form.zone_id]
  );

  const submitting = submitState === 'submitting';

  const update = (field) => (e) => {
    const value = e.target.value;
    setForm(f => ({ ...f, [field]: value }));
    if (errors[field]) setErrors(errs => { const next = { ...errs }; delete next[field]; return next; });
    if (submitState === 'error') setSubmitState('idle');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    const validation = validateRequestForm(form, options);
    setErrors(validation);
    if (Object.keys(validation).length > 0) {
      setSubmitState('error');
      setSubmitError('Please correct the highlighted fields.');
      return;
    }

    setSubmitState('submitting');
    setSubmitError(null);
    setCreated(null);
    try {
      const { status, data } = await api.createEmergencyRequest(buildRequestPayload(form, idempotencyKey));
      setCreated({ ...data, httpStatus: status });
      setSubmitState('success');
      onCreated?.(data);
      // Fresh draft: new idempotency key, keep requester for follow-up requests.
      setForm(f => ({ ...EMPTY_FORM, requester_id: f.requester_id }));
      setErrors({});
      setIdempotencyKey(newIdempotencyKey());
    } catch (err) {
      setErrors(err.fieldErrors || {});
      setSubmitError(errorMessageFor(err));
      setSubmitState('error');
      // Keep the same idempotency key: a retry of THIS draft must not create a duplicate.
    }
  };

  const fieldProps = (id) => ({
    id,
    name: id,
    value: form[id],
    onChange: update(id),
    disabled: submitting,
    'aria-invalid': errors[id] ? 'true' : undefined,
    'aria-describedby': errors[id] ? `${id}-error` : undefined,
  });

  return (
    <section className="card" aria-label="Create Emergency Request" style={{ marginBottom: 16 }}>
      <div className="card-header">
        <div className="card-heading">
          <h2 className="card-title"><PlusCircle size={16} className="card-title-icon" />Create Emergency Request</h2>
          <div className="card-subtitle">
            Stored in one PostgreSQL transaction with its <code>request_pool_dependency</code> entry, an <code>event_outbox</code> event
            and an audit record — immediately visible to the matching engine (<code>POST /api/v1/requests</code>).
          </div>
        </div>
        {onClose && (
          <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Close request form"><X size={14} /></button>
        )}
      </div>

      {optionsState === 'loading' && <LoadingState compact label="Loading requesters and zones from the database…" />}

      {optionsState === 'error' && (
        <ErrorState title="The request form could not load its reference data" message={optionsError} onRetry={loadOptions} />
      )}

      {optionsState === 'ready' && (options.requesters.length === 0 || options.zones.length === 0) && (
        <div className="alert alert-error" role="alert">
          <AlertTriangle size={16} />
          <div>
            {options.requesters.length === 0 && 'No requesters are visible to your role in the database. '}
            {options.zones.length === 0 && 'No zones exist in the database. '}
            Load the seed data (<code>scripts/seed_data.sql</code>) before creating requests.
          </div>
        </div>
      )}

      {submitState === 'success' && created && (
        <div className="alert alert-success" role="status">
          <CheckCircle2 size={18} />
          <div className="alert-body">
            <strong>
              {created.idempotent_replay
                ? 'This request was already submitted — showing the stored record (no duplicate created).'
                : 'Emergency request created and stored in PostgreSQL.'}
            </strong>
            <dl className="created-summary">
              <div><dt>Request ID</dt><dd style={{ fontFamily: 'monospace' }}>{created.request_id}</dd></div>
              <div><dt>Resource type</dt><dd>{label(RESOURCE_LABELS, created.resource_type_needed)}</dd></div>
              <div><dt>Quantity</dt><dd>{created.quantity_requested}</dd></div>
              <div><dt>Urgency</dt><dd><span className={`badge badge-${created.urgency_level}`}>{created.urgency_level}</span></dd></div>
              <div><dt>Zone / location</dt><dd>{created.zone_name}{created.latitude != null && ` (${created.latitude.toFixed(4)}, ${created.longitude.toFixed(4)})`}</dd></div>
              <div><dt>Initial status (DB default)</dt><dd><span className={`badge badge-${created.status}`}>{created.status}</span></dd></div>
              {created.pool_dependency && (
                <div><dt>Registered pool</dt><dd>{created.pool_dependency.resource_type} × {created.pool_dependency.mobility_class}</dd></div>
              )}
            </dl>
          </div>
          <button type="button" aria-label="Dismiss" className="btn btn-ghost btn-sm btn-icon" onClick={() => setSubmitState('idle')}>
            <X size={13} />
          </button>
        </div>
      )}

      {submitState === 'error' && submitError && (
        <div className="alert alert-error" role="alert">
          <AlertTriangle size={16} />
          <div>{submitError}</div>
        </div>
      )}

      {optionsState === 'ready' && (
        <form onSubmit={handleSubmit} noValidate aria-busy={submitting}>
          <div className="request-form-grid">
            <Field id="requester_id" labelText="Requester" required error={errors.requester_id}>
              <select className="form-select" {...fieldProps('requester_id')}>
                <option value="">Select requester…</option>
                {options.requesters.map(r => (
                  <option key={r.requester_id} value={r.requester_id}>
                    {r.name} ({r.requester_type.replace(/_/g, ' ')}){r.verified_flag ? ' ✓' : ''}
                  </option>
                ))}
              </select>
            </Field>

            <Field id="resource_type_needed" labelText="Resource Type" required error={errors.resource_type_needed}>
              <select className="form-select" {...fieldProps('resource_type_needed')}>
                <option value="">Select resource type…</option>
                {options.resource_types.map(t => <option key={t} value={t}>{label(RESOURCE_LABELS, t)}</option>)}
              </select>
            </Field>

            <Field id="quantity_requested" labelText="Quantity Required" required error={errors.quantity_requested}>
              <input className="form-input" type="number" inputMode="decimal" min="0.01" step="0.01"
                     placeholder="e.g. 50" {...fieldProps('quantity_requested')} />
            </Field>

            <Field id="urgency_level" labelText="Urgency" required error={errors.urgency_level}>
              <select className="form-select" {...fieldProps('urgency_level')}>
                <option value="">Select urgency…</option>
                {options.urgency_levels.map(u => <option key={u} value={u}>{label(URGENCY_LABELS, u)}</option>)}
              </select>
            </Field>

            <Field id="zone_id" labelText="Zone / Location" required error={errors.zone_id}
                   hint={selectedZone ? `${selectedZone.zone_type} · risk ${selectedZone.risk_level}` : undefined}>
              <select className="form-select" {...fieldProps('zone_id')}>
                <option value="">Select zone…</option>
                {options.zones.map(z => (
                  <option key={z.zone_id} value={z.zone_id}>{z.zone_name} ({z.zone_type})</option>
                ))}
              </select>
            </Field>

            <Field id="mobility_requirement" labelText="Mobility / Accessibility Requirement" error={errors.mobility_requirement}
                   hint="Registers the request in the matching pool for this access mode.">
              <select className="form-select" {...fieldProps('mobility_requirement')}>
                {options.mobility_classes.map(m => <option key={m} value={m}>{label(MOBILITY_LABELS, m)}</option>)}
              </select>
            </Field>

            <Field id="latitude" labelText="Latitude (optional)" error={errors.latitude}
                   hint={selectedZone?.latitude != null ? `Blank = zone point ${selectedZone.latitude.toFixed(4)}` : 'Blank = zone location'}>
              <input className="form-input" type="number" step="any" min="-90" max="90" placeholder="e.g. 13.0827" {...fieldProps('latitude')} />
            </Field>

            <Field id="longitude" labelText="Longitude (optional)" error={errors.longitude}
                   hint={selectedZone?.longitude != null ? `Blank = zone point ${selectedZone.longitude.toFixed(4)}` : 'Blank = zone location'}>
              <input className="form-input" type="number" step="any" min="-180" max="180" placeholder="e.g. 80.2707" {...fieldProps('longitude')} />
            </Field>

            <Field id="needed_by" labelText="Needed By (optional)" error={errors.needed_by}>
              <input className="form-input" type="datetime-local" {...fieldProps('needed_by')} />
            </Field>

            <div className="span-3">
              <Field id="description" labelText="Description" error={errors.description}
                     hint={`${form.description.length}/${MAX_DESCRIPTION} characters`}>
                <textarea className="form-input" rows={3} maxLength={MAX_DESCRIPTION}
                          placeholder="e.g. Medical supplies required for flooded shelter" {...fieldProps('description')} />
              </Field>
            </div>
          </div>

          <div className="form-footer">
            <span className="form-footer-note">
              <span className="required-mark">*</span> required · acting as role <code>{options.current_role}</code>
            </span>
            <button type="submit" className="btn btn-emergency" disabled={submitting}>
              {submitting ? <><Loader2 size={15} className="spin" /> Submitting…</> : <><Send size={15} /> Submit Emergency Request</>}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
