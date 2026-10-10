// Shared display helpers (formatting + human labels). Values shown in the UI
// always come from the API; these only decide how they are written.

export const fmtQty = (v) => (v == null || v === '' ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }));
export const fmtTime = (v) => (v ? new Date(v).toLocaleString() : '—');
export const fmtDate = (v) => (v ? new Date(v).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : '—');
export const fmtClock = (v) => (v ? new Date(v).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—');
export const short = (id, n = 8) => (id ? String(id).substring(0, n) : '—');
export const pct = (part, whole) => (whole > 0 ? Math.max(0, Math.min(100, (Number(part) / Number(whole)) * 100)) : 0);
export const humanize = (s) => (s == null ? '—' : String(s).replace(/_/g, ' '));

export function relativeTime(fromIso, nowMs = Date.now()) {
  if (!fromIso) return '';
  const s = Math.max(0, Math.round((nowMs - new Date(fromIso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export const URGENCY_LABELS = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' };

// Request tracking stages (derived by the backend, see services/tracking_rules.py).
export const STAGE_LABELS = {
  pending: 'Pending',
  matching: 'Matching',
  partially_fulfilled: 'Partially Fulfilled',
  fulfilled: 'Fulfilled',
  cancelled: 'Cancelled',
  expired: 'Expired',
};

export const ALLOCATION_STATUS_LABELS = {
  pending: 'Pending', matched: 'Matched', proposed: 'Proposed', reserved: 'Reserved', dispatched: 'Dispatched',
  in_transit: 'In transit', delivered: 'Delivered', confirmed: 'Confirmed', fulfilled: 'Fulfilled',
  cancelled: 'Cancelled', rejected: 'Rejected', expired: 'Expired', reassigned: 'Reassigned',
};
