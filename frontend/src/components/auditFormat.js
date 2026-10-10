// Turns allocation_history rows (written by database triggers) into readable
// events. Pure presentation: no values are added or changed.
import { humanize, short } from './format';

const KEY_FIELDS = [
  'status', 'allocation_status', 'quantity_total', 'quantity_available', 'quantity_fulfilled', 'quantity_requested',
  'quantity', 'quantity_allocated', 'current_zone_id', 'resource_subtype', 'capabilities', 'condition_notes', 'lease_expires_at',
];
const IDS = new Set(['current_zone_id']);

const fmtVal = (k, v) => {
  if (v == null) return '—';
  if (IDS.has(k)) return short(v);
  if (typeof v === 'object') return k === 'capabilities' && v.mobility_class ? `mobility ${v.mobility_class}` : JSON.stringify(v);
  if (typeof v === 'string' && /^\d{4}-\d\d-\d\dT/.test(v)) return new Date(v).toLocaleString();
  return String(v);
};

function changes(log) {
  const n = log.new_value || {};
  const o = log.old_value || {};
  if (!log.old_value) return [];
  return KEY_FIELDS
    .filter(k => k in n && JSON.stringify(n[k]) !== JSON.stringify(o[k]))
    .slice(0, 4)
    .map(k => ({ field: humanize(k), from: fmtVal(k, o[k]), to: fmtVal(k, n[k]) }));
}

export function describeAuditEvent(log) {
  const n = log.new_value || {};
  const o = log.old_value || {};
  const type = log.entity_type;
  let title;
  if (type === 'request') {
    title = log.action === 'created' ? 'Request created'
      : log.action === 'status_changed' ? `Request ${humanize(o.status)} → ${humanize(n.status)}` : `Request ${humanize(log.action)}`;
  } else if (type === 'reservation') {
    title = log.action === 'created' ? `Lease created${n.quantity != null ? ` · ${n.quantity}` : ''}`
      : log.action === 'status_changed' ? `Lease ${humanize(o.status)} → ${humanize(n.status)}` : `Lease ${humanize(log.action)}`;
  } else if (type === 'allocation') {
    title = log.action === 'created' ? `Allocation created (${humanize(n.allocation_status)})`
      : log.action === 'status_changed' ? `Allocation ${humanize(o.allocation_status)} → ${humanize(n.allocation_status)}` : `Allocation ${humanize(log.action)}`;
  } else if (type === 'resource') {
    title = log.action === 'created' ? 'Resource registered'
      : log.action === 'status_changed' ? `Resource ${humanize(o.status)} → ${humanize(n.status)}`
      : log.action === 'quantity_updated' ? 'Resource stock changed' : 'Resource updated';
  } else {
    title = `${humanize(type)} ${humanize(log.action)}`;
  }
  return {
    kind: type,
    title,
    action: log.action,
    entity: `${humanize(type)} ${short(log.entity_id)}`,
    changes: log.action === 'created' ? [] : changes(log),
    remarks: log.remarks || null,
    isTransition: log.action === 'status_changed',
  };
}
