// Presentation of the request lifecycle. Nothing here changes state: every
// stage is derived from data the API already returns (tracking response or the
// request list row). The database (request status guard + allocation state
// machine) remains the authority on what is legal.
//
//   PENDING    request stored, nothing assigned yet
//   MATCHED    matching engine leased resources (reservation + matching_decision)
//   RESERVED   a lease was converted into an allocation (allocation_status 'reserved')
//   DISPATCHED allocation dispatched / in transit / delivered
//   CONFIRMED  delivery confirmed (quantity_fulfilled > 0)
//   FULFILLED  request fulfilled (database status)

import { fmtQty } from './format';

export const LIFECYCLE = [
  { key: 'pending', label: 'Pending', hint: 'Request recorded' },
  { key: 'matched', label: 'Matched', hint: 'Resources leased' },
  { key: 'reserved', label: 'Reserved', hint: 'Allocation created' },
  { key: 'dispatched', label: 'Dispatched', hint: 'On the way' },
  { key: 'confirmed', label: 'Confirmed', hint: 'Delivery confirmed' },
  { key: 'fulfilled', label: 'Fulfilled', hint: 'Need fully met' },
];

const LIVE_ALLOCATION = ['pending', 'matched', 'proposed', 'reserved', 'dispatched', 'in_transit', 'delivered', 'confirmed', 'fulfilled'];
const DISPATCHED_OR_LATER = ['dispatched', 'in_transit', 'delivered', 'confirmed', 'fulfilled'];
const TERMINAL = ['cancelled', 'expired'];

function build(reachedIndex, terminal, metas) {
  return LIFECYCLE.map((s, i) => {
    let state;
    if (i <= reachedIndex) state = 'done';
    else if (terminal) state = 'skipped';
    else if (i === reachedIndex + 1) state = 'current';
    else state = 'upcoming';
    return { ...s, state, meta: metas?.[s.key] || null };
  });
}

/** Full lifecycle from GET /requests/{id}/tracking. */
export function lifecycleFromTracking(data) {
  const allocs = data.allocations || [];
  const res = data.reservations || [];
  const q = data.quantities || {};
  const live = allocs.filter(a => LIVE_ALLOCATION.includes(a.allocation_status));
  const fulfilled = Number(q.fulfilled || 0);
  const reached = {
    pending: true,
    matched: res.length > 0 || allocs.length > 0 || fulfilled > 0,
    reserved: live.length > 0 || fulfilled > 0,
    dispatched: allocs.some(a => DISPATCHED_OR_LATER.includes(a.allocation_status)) || fulfilled > 0,
    confirmed: fulfilled > 0,
    fulfilled: data.stage === 'fulfilled',
  };
  let idx = 0;
  LIFECYCLE.forEach((s, i) => { if (reached[s.key]) idx = i; });
  const activeLeases = res.filter(r => r.lease_active);
  const metas = {
    pending: null,
    matched: res.length ? `${res.length} lease${res.length > 1 ? 's' : ''}${activeLeases.length ? ` · ${fmtQty(q.reserved)} held` : ''}` : null,
    reserved: live.length ? `${live.length} allocation${live.length > 1 ? 's' : ''}` : null,
    dispatched: allocs.filter(a => ['dispatched', 'in_transit', 'delivered'].includes(a.allocation_status)).length
      ? `${allocs.filter(a => ['dispatched', 'in_transit', 'delivered'].includes(a.allocation_status)).length} in delivery` : null,
    confirmed: fulfilled > 0 ? `${fmtQty(fulfilled)} of ${fmtQty(q.requested)}` : null,
    fulfilled: data.stage === 'fulfilled' ? 'Complete' : (fulfilled > 0 ? `${fmtQty(q.remaining)} remaining` : null),
  };
  return { steps: build(idx, TERMINAL.includes(data.stage), metas), terminal: TERMINAL.includes(data.stage) ? data.stage : null };
}

/**
 * Coarse phase from a request LIST row (tracking_stage + quantity_reserved /
 * quantity_in_progress / quantity_fulfilled). The list does not say whether an
 * in-flight allocation was dispatched yet, so that case is shown as "Allocated".
 */
export function phaseFromRow(row) {
  const stage = row.tracking_stage || row.status;
  const fulfilled = Number(row.quantity_fulfilled || 0);
  const leased = Number(row.quantity_reserved || 0);
  const inFlight = Number(row.quantity_in_progress || 0);
  if (stage === 'cancelled' || stage === 'expired') return { key: stage, label: stage === 'cancelled' ? 'Cancelled' : 'Expired', index: -1, tone: 'gray' };
  if (stage === 'fulfilled') return { key: 'fulfilled', label: 'Fulfilled', index: 5, tone: 'green' };
  if (inFlight > 0) return { key: 'allocated', label: 'Allocated · in delivery', index: 2, tone: 'blue', partial: fulfilled > 0 };
  if (leased > 0) return { key: 'matched', label: 'Matched · lease held', index: 1, tone: 'blue', partial: fulfilled > 0 };
  if (fulfilled > 0) return { key: 'confirmed', label: 'Partially confirmed', index: 4, tone: 'violet', partial: true };
  return { key: 'pending', label: 'Awaiting match', index: 0, tone: 'amber' };
}

/** What can happen next, for the list row (role-aware wording only). */
export function nextStepFromRow(row, canManage) {
  const phase = phaseFromRow(row);
  switch (phase.key) {
    case 'pending': return canManage ? 'Run matching' : 'Waiting for a coordinator to match';
    case 'matched': return canManage ? 'Allocate the leased resources' : 'Resources leased by a coordinator';
    case 'allocated': return canManage ? 'Dispatch / confirm delivery' : 'Delivery in progress';
    case 'confirmed': return canManage ? `Match remaining ${fmtQty(row.quantity_remaining)}` : `${fmtQty(row.quantity_remaining)} still needed`;
    case 'fulfilled': return 'Complete';
    default: return 'No further action';
  }
}

/** Next step for the tracking panel (exact, from the tracking response). */
export function nextStepFromTracking(data) {
  if (data.stage === 'fulfilled') return { text: 'Request fulfilled — no further action.', tone: 'green' };
  if (TERMINAL.includes(data.stage)) return { text: `Request ${data.stage} — no further action.`, tone: 'gray' };
  const allocs = data.allocations || [];
  const can = data.can_manage;
  const leases = (data.reservations || []).filter(r => r.lease_active);
  if (allocs.some(a => ['dispatched', 'in_transit', 'delivered'].includes(a.allocation_status))) {
    return { text: can ? 'Confirm delivery of the dispatched allocation.' : 'Delivery in progress — awaiting confirmation by a coordinator.', tone: 'blue' };
  }
  if (allocs.some(a => a.allocation_status === 'reserved')) {
    return { text: can ? 'Dispatch the reserved allocation.' : 'Allocation reserved — awaiting dispatch.', tone: 'blue' };
  }
  if (leases.length) {
    return { text: can ? `Allocate ${leases.length === 1 ? 'the leased resource' : `the ${leases.length} leased resources`} (or release the lease).` : 'Resources leased — awaiting allocation by a coordinator.', tone: 'blue' };
  }
  if (Number(data.quantity_to_cover) > 0) {
    return { text: can ? `Run matching for the ${fmtQty(data.quantity_to_cover)} still to cover.` : 'Waiting for a coordinator to run matching.', tone: 'amber' };
  }
  return { text: 'Nothing left to cover right now.', tone: 'gray' };
}
