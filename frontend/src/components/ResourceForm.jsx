import React, { useState } from 'react';
import { api } from '../api/client';
import { Field } from './CreateRequestForm';
import { RESOURCE_TYPE_LABELS, MOBILITY_LABELS, STATUS_LABELS, label, quantityError, coordinateErrors } from './resourceLabels';
import { PlusCircle, Loader2, AlertTriangle, X } from 'lucide-react';

const EMPTY = {
  owner_id: '', resource_type: '', resource_subtype: '', quantity_total: '', quantity_available: '',
  unit_of_measure: 'units', status: 'available', current_zone_id: '', mobility_class: '',
  latitude: '', longitude: '', condition_notes: '',
};

export function validateResourceForm(form, options) {
  const errors = {};
  const owners = new Set((options?.owners || []).map(o => o.owner_id));
  const zones = new Set((options?.zones || []).map(z => z.zone_id));
  if (options?.current_role === 'coordinator' && !owners.has(form.owner_id)) errors.owner_id = 'Select the owner.';
  if (!(options?.resource_types || []).includes(form.resource_type)) errors.resource_type = 'Select the resource type.';
  const qt = quantityError(form.quantity_total);
  if (qt) errors.quantity_total = qt;
  const qa = quantityError(form.quantity_available, { required: false });
  if (qa) errors.quantity_available = qa;
  else if (!qt && String(form.quantity_available).trim() !== '' && Number(form.quantity_available) > Number(form.quantity_total)) {
    errors.quantity_available = 'Available cannot exceed the total.';
  }
  if (!(options?.units || []).includes(form.unit_of_measure)) errors.unit_of_measure = 'Select a unit.';
  if (!(options?.operator_statuses || []).includes(form.status)) errors.status = 'Select a status.';
  if (!zones.has(form.current_zone_id)) errors.current_zone_id = 'Select the zone.';
  if (form.mobility_class && !(options?.mobility_classes || []).includes(form.mobility_class)) errors.mobility_class = 'Select a valid mobility class.';
  Object.assign(errors, coordinateErrors(form.latitude, form.longitude));
  if (form.resource_subtype.trim().length > 100) errors.resource_subtype = 'At most 100 characters.';
  if (form.condition_notes.trim().length > 1000) errors.condition_notes = 'At most 1000 characters.';
  return errors;
}

export function buildCreatePayload(form, options) {
  const p = {
    current_zone_id: form.current_zone_id,
    resource_type: form.resource_type,
    quantity_total: Number(form.quantity_total),
    unit_of_measure: form.unit_of_measure,
    status: form.status,
  };
  if (options?.current_role === 'coordinator') p.owner_id = form.owner_id;
  if (String(form.quantity_available).trim() !== '') p.quantity_available = Number(form.quantity_available);
  if (form.resource_subtype.trim()) p.resource_subtype = form.resource_subtype.trim();
  if (form.condition_notes.trim()) p.condition_notes = form.condition_notes.trim();
  if (form.mobility_class) p.mobility_class = form.mobility_class;
  if (String(form.latitude).trim() !== '') { p.latitude = Number(form.latitude); p.longitude = Number(form.longitude); }
  return p;
}

export default function ResourceForm({ options, onCreated, onCancel }) {
  const [form, setForm] = useState(() => ({
    ...EMPTY,
    owner_id: options.owners.length === 1 ? options.owners[0].owner_id : '',
  }));
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const set = (k) => (e) => {
    const v = e.target.value;
    setForm(f => ({ ...f, [k]: v }));
    if (errors[k]) setErrors(x => { const n = { ...x }; delete n[k]; return n; });
  };
  const fp = (id) => ({ id, name: id, value: form[id], onChange: set(id), disabled: submitting,
    'aria-invalid': errors[id] ? 'true' : undefined, 'aria-describedby': errors[id] ? `${id}-error` : undefined });

  const submit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    const v = validateResourceForm(form, options);
    setErrors(v);
    if (Object.keys(v).length) { setError('Please correct the highlighted fields.'); return; }
    setSubmitting(true); setError(null);
    try {
      const result = await api.createResource(buildCreatePayload(form, options));
      onCreated?.(result);
      setForm(f => ({ ...EMPTY, owner_id: f.owner_id }));
    } catch (err) {
      setErrors(err.fieldErrors || {});
      setError(err.kind === 'network' ? err.message : `Could not add the resource: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const zone = options.zones.find(z => z.zone_id === form.current_zone_id);

  return (
    <section className="card" aria-label="Add Resource">
      <div className="card-header">
        <div className="card-heading">
          <h2 className="card-title" id="add-resource-title"><PlusCircle size={16} className="card-title-icon" /> Add Resource</h2>
          <div className="card-subtitle">
            Submits to <code>POST /api/v1/resources</code>. The database records the initial stock in <code>resource_ledger</code>,
            the position in <code>resource_location_history</code> and an audit row in <code>allocation_history</code>.
          </div>
        </div>
        <button type="button" className="btn btn-ghost btn-sm btn-icon" onClick={onCancel} aria-label="Close add resource"><X size={14} /></button>
      </div>

      {error && <div className="alert alert-error" role="alert"><AlertTriangle size={16} /><div>{error}</div></div>}

      <form onSubmit={submit} noValidate aria-busy={submitting}>
        <div className="form-grid-2">
          <div className="form-section-label">Identity</div>
          {options.current_role === 'coordinator' ? (
            <Field id="owner_id" labelText="Owner" required error={errors.owner_id}>
              <select className="form-select" {...fp('owner_id')}>
                <option value="">Select owner…</option>
                {options.owners.map(o => <option key={o.owner_id} value={o.owner_id}>{o.name} ({o.owner_type})</option>)}
              </select>
            </Field>
          ) : (
            <Field id="owner_display" labelText="Owner">
              <input className="form-input" id="owner_display" value={options.owners[0]?.name || 'your organisation'} disabled />
            </Field>
          )}
          <Field id="resource_type" labelText="Resource Type" required error={errors.resource_type}>
            <select className="form-select" {...fp('resource_type')}>
              <option value="">Select type…</option>
              {options.resource_types.map(t => <option key={t} value={t}>{label(RESOURCE_TYPE_LABELS, t)}</option>)}
            </select>
          </Field>
          <Field id="resource_subtype" labelText="Subtype / Description" error={errors.resource_subtype}>
            <input className="form-input" maxLength={100} placeholder="e.g. 25 kVA diesel generator" {...fp('resource_subtype')} />
          </Field>
          <div className="form-section-label">Stock</div>
          <Field id="quantity_total" labelText="Total Quantity" required error={errors.quantity_total}>
            <input className="form-input" type="number" min="0" step="0.01" placeholder="e.g. 10" {...fp('quantity_total')} />
          </Field>
          <Field id="quantity_available" labelText="Available Now (optional)" error={errors.quantity_available} hint="Blank = all of the total">
            <input className="form-input" type="number" min="0" step="0.01" {...fp('quantity_available')} />
          </Field>
          <Field id="unit_of_measure" labelText="Unit" required error={errors.unit_of_measure}>
            <select className="form-select" {...fp('unit_of_measure')}>
              {options.units.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          </Field>
          <div className="form-section-label">Location &amp; availability</div>
          <Field id="current_zone_id" labelText="Zone" required error={errors.current_zone_id}
                 hint={zone ? `${zone.zone_type} · risk ${zone.risk_level}` : undefined}>
            <select className="form-select" {...fp('current_zone_id')}>
              <option value="">Select zone…</option>
              {options.zones.map(z => <option key={z.zone_id} value={z.zone_id}>{z.zone_name} ({z.zone_type})</option>)}
            </select>
          </Field>
          <Field id="latitude" labelText="Latitude (optional)" error={errors.latitude} hint="Blank = zone location">
            <input className="form-input" type="number" step="any" {...fp('latitude')} />
          </Field>
          <Field id="longitude" labelText="Longitude (optional)" error={errors.longitude} hint="Blank = zone location">
            <input className="form-input" type="number" step="any" {...fp('longitude')} />
          </Field>
          <Field id="status" labelText="Availability" required error={errors.status}>
            <select className="form-select" {...fp('status')}>
              {options.operator_statuses.map(s => <option key={s} value={s}>{label(STATUS_LABELS, s)}</option>)}
            </select>
          </Field>
          <Field id="mobility_class" labelText="Mobility Class" error={errors.mobility_class}>
            <select className="form-select" {...fp('mobility_class')}>
              <option value="">Not specified</option>
              {options.mobility_classes.map(m => <option key={m} value={m}>{label(MOBILITY_LABELS, m)}</option>)}
            </select>
          </Field>
          <div className="span-2">
            <Field id="condition_notes" labelText="Condition Notes" error={errors.condition_notes}>
              <input className="form-input" maxLength={1000} placeholder="e.g. serviced 2 days ago" {...fp('condition_notes')} />
            </Field>
          </div>
        </div>
        <div className="form-footer">
          <span className="form-footer-note"><span className="required-mark">*</span> required</span>
          <div className="btn-group">
            <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={submitting}>Cancel</button>
            <button type="submit" className="btn" disabled={submitting}>
              {submitting ? <><Loader2 size={15} className="spin" /> Saving…</> : <><PlusCircle size={15} /> Add Resource</>}
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}
