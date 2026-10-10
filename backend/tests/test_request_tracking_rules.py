"""Unit tests for the Request Status Tracking rules (no database needed).

The database-side lifecycle (guard trigger, allocation roll-up, audit rows)
is exercised against the live database in test_request_tracking_api.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.tracking_rules import (
    DB_STATUSES, TRACKING_STEPS, build_steps, derive_tracking_stage, summarize, _build_timeline,
)


@pytest.mark.parametrize("db_status,active,expected", [
    ("open", False, "pending"),
    ("pending", False, "pending"),
    ("open", True, "matching"),
    ("pending", True, "matching"),
    ("partially_fulfilled", False, "partially_fulfilled"),
    ("partially_fulfilled", True, "partially_fulfilled"),
    ("fulfilled", False, "fulfilled"),
    ("cancelled", True, "cancelled"),
    ("expired", False, "expired"),
])
def test_derive_tracking_stage(db_status, active, expected):
    assert derive_tracking_stage(db_status, active) == expected


@pytest.mark.parametrize("bogus", ["matching", "proposed", "reserved", "", "FULFILLED"])
def test_unknown_database_status_is_rejected(bogus):
    # The tracking layer never invents or accepts statuses outside the DB CHECK constraint.
    with pytest.raises(ValueError):
        derive_tracking_stage(bogus, False)


def test_every_db_status_maps_to_a_stage():
    stages = {k for k, _ in TRACKING_STEPS} | {"cancelled", "expired"}
    for s in DB_STATUSES:
        assert derive_tracking_stage(s, False) in stages
        assert derive_tracking_stage(s, True) in stages


def test_steps_progression():
    states = lambda stage: [s["state"] for s in build_steps(stage, True, 0)]
    assert states("pending") == ["current", "upcoming", "upcoming", "upcoming"]
    assert states("matching") == ["complete", "current", "upcoming", "upcoming"]
    assert states("partially_fulfilled") == ["complete", "complete", "current", "upcoming"]
    assert states("fulfilled") == ["complete"] * 4
    assert [s["label"] for s in build_steps("pending", False, 0)] == ["Pending", "Matching", "Partially Fulfilled", "Fulfilled"]


def test_terminal_steps_show_what_was_reached():
    assert [s["state"] for s in build_steps("cancelled", False, 0)] == ["complete", "skipped", "skipped", "skipped"]
    assert [s["state"] for s in build_steps("cancelled", True, 0)] == ["complete", "complete", "skipped", "skipped"]
    assert [s["state"] for s in build_steps("expired", True, 4)] == ["complete", "complete", "complete", "skipped"]


def test_summarize_quantities():
    row = {"status": "partially_fulfilled", "quantity_requested": 15.0, "quantity_fulfilled": 10.0}
    s = summarize(row, {"quantity_reserved": 0.0, "quantity_in_progress": 5.0, "ever_matched": True})
    assert s["tracking_stage"] == "partially_fulfilled"
    assert s["quantity_remaining"] == 5.0 and s["quantity_in_progress"] == 5.0 and s["matching_active"] is True

    fresh = summarize({"status": "open", "quantity_requested": 50, "quantity_fulfilled": 0}, None)
    assert fresh["tracking_stage"] == "pending" and fresh["quantity_remaining"] == 50.0 and fresh["matching_active"] is False

    reserved = summarize({"status": "open", "quantity_requested": 50, "quantity_fulfilled": 0},
                         {"quantity_reserved": 20.0, "quantity_in_progress": 0.0, "ever_matched": True})
    assert reserved["tracking_stage"] == "matching"


def test_timeline_is_ordered_and_falls_back_for_legacy_rows():
    t0 = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
    history = [
        {"entity_type": "request", "action": "status_changed", "allocation_id": None, "performed_at": t0 + timedelta(hours=2),
         "old_value": {"status": "open"}, "new_value": {"status": "partially_fulfilled", "quantity_fulfilled": 10, "quantity_requested": 15}, "remarks": None},
        {"entity_type": "allocation", "action": "created", "allocation_id": "21111111-bbbb", "performed_at": t0 + timedelta(hours=1),
         "old_value": None, "new_value": {"allocation_status": "matched", "quantity_allocated": 10}, "remarks": None},
    ]
    reservations = [{"reservation_id": "aaaaaaaa-0000", "quantity": 5, "resource_type": "generator", "status": "expired",
                     "lease_expires_at": t0 + timedelta(hours=1), "created_at": t0 + timedelta(minutes=10), "updated_at": t0 + timedelta(hours=1, minutes=1)}]
    tl = _build_timeline({"requested_at": t0}, reservations, history)
    assert [e["at"] for e in tl] == sorted(e["at"] for e in tl)
    assert tl[0]["label"] == "Request submitted"           # no 'created' audit row (pre-0010 data)
    assert any(e["label"].endswith("expired") for e in tl)
    assert any("open → partially_fulfilled" in e["label"] for e in tl)
