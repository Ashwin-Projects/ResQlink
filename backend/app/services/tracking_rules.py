"""Pure Request Status Tracking rules (no database / web imports).

Maps the database lifecycle of emergency_requests.status onto the tracking
stages shown in the UI:

    Pending -> Matching -> Partially Fulfilled -> Fulfilled   (+ terminal cancelled / expired)

* pending / matching  <- DB status 'open' or 'pending'; "matching" is DERIVED
  (the request currently holds an active, unexpired leased reservation or an
  allocation that is not yet confirmed). It is never stored.
* partially_fulfilled / fulfilled <- set only by the database when an
  allocation is confirmed (fn_allocations_on_status_change).
* cancelled / expired <- terminal DB statuses.
"""
from typing import Optional


DB_STATUSES = ("open", "pending", "partially_fulfilled", "fulfilled", "cancelled", "expired")
TERMINAL_STATUSES = ("fulfilled", "cancelled", "expired")
# Allocation states that have not yet been confirmed/fulfilled nor died.
IN_FLIGHT_ALLOCATION_STATUSES = ("pending", "matched", "proposed", "reserved", "dispatched", "in_transit", "delivered")

TRACKING_STEPS = (
    ("pending", "Pending"),
    ("matching", "Matching"),
    ("partially_fulfilled", "Partially Fulfilled"),
    ("fulfilled", "Fulfilled"),
)


def derive_tracking_stage(db_status: str, has_active_matching: bool) -> str:
    """Map the database status (+ live reservation/allocation activity) to the tracking stage."""
    if db_status in ("partially_fulfilled", "fulfilled", "cancelled", "expired"):
        return db_status
    if db_status in ("open", "pending"):
        return "matching" if has_active_matching else "pending"
    raise ValueError(f"Unknown emergency request status: {db_status!r}")


def build_steps(stage: str, ever_matched: bool, quantity_fulfilled: float) -> list:
    """Stepper states: complete | current | upcoming | skipped."""
    keys = [k for k, _ in TRACKING_STEPS]
    if stage in ("cancelled", "expired"):
        reached = {"pending"}
        if ever_matched:
            reached.add("matching")
        if quantity_fulfilled > 0:
            reached.update({"matching", "partially_fulfilled"})
        return [{"key": k, "label": label, "state": "complete" if k in reached else "skipped"}
                for k, label in TRACKING_STEPS]
    current = keys.index(stage)
    steps = []
    for i, (k, label) in enumerate(TRACKING_STEPS):
        if i < current or stage == "fulfilled":
            state = "complete"
        elif i == current:
            state = "current"
        else:
            state = "upcoming"
        steps.append({"key": k, "label": label, "state": state})
    return steps


def summarize(request: dict, progress: Optional[dict]) -> dict:
    """Tracking fields added to a request read-model row."""
    progress = progress or {"quantity_reserved": 0.0, "quantity_in_progress": 0.0, "ever_matched": False}
    requested = float(request["quantity_requested"])
    fulfilled = float(request["quantity_fulfilled"])
    active = progress["quantity_reserved"] > 0 or progress["quantity_in_progress"] > 0
    stage = derive_tracking_stage(request["status"], active)
    return {
        "tracking_stage": stage,
        "quantity_remaining": max(0.0, round(requested - fulfilled, 2)),
        "quantity_reserved": progress["quantity_reserved"],
        "quantity_in_progress": progress["quantity_in_progress"],
        "matching_active": active,
        "ever_matched": progress["ever_matched"],
    }


def _num(v):
    return float(v) if v is not None else None


def _build_timeline(request: dict, reservations: list, history: list) -> list:
    events = []
    has_created_audit = False
    for h in history:
        new = h["new_value"] or {}
        old = h["old_value"] or {}
        if h["entity_type"] == "request":
            if h["action"] == "created":
                has_created_audit = True
                events.append({"at": h["performed_at"], "kind": "request_created", "label": "Request created", "detail": h["remarks"]})
            elif h["action"] == "status_changed":
                events.append({"at": h["performed_at"], "kind": "request_status",
                               "label": f"Status {old.get('status')} → {new.get('status')}",
                               "detail": f"fulfilled {new.get('quantity_fulfilled')} of {new.get('quantity_requested')}"})
        elif h["entity_type"] == "allocation":
            short = str(h["allocation_id"])[:8]
            if h["action"] == "created":
                events.append({"at": h["performed_at"], "kind": "allocation",
                               "label": f"Allocation {short} created ({new.get('allocation_status')})",
                               "detail": f"quantity {new.get('quantity_allocated')}"})
            else:
                events.append({"at": h["performed_at"], "kind": "allocation",
                               "label": f"Allocation {short}: {old.get('allocation_status')} → {new.get('allocation_status')}",
                               "detail": h["remarks"]})
    if not has_created_audit:
        # Rows created before migration 0010 have no audit row.
        events.append({"at": request["requested_at"], "kind": "request_created", "label": "Request submitted", "detail": None})
    for r in reservations:
        short = str(r["reservation_id"])[:8]
        events.append({"at": r["created_at"], "kind": "reservation",
                       "label": f"Reservation {short} leased ({_num(r['quantity'])} × {r['resource_type']})",
                       "detail": f"lease until {r['lease_expires_at'].strftime('%Y-%m-%d %H:%M %Z').strip()}"})
        if r["status"] != "active":
            events.append({"at": r["updated_at"], "kind": "reservation",
                           "label": f"Reservation {short} {r['status']}", "detail": None})
    events.sort(key=lambda e: e["at"])
    return events


