-- ============================================================================
-- ResQLink — Seed Data for Local Development
-- Deliberately exercises the Phase 1 edge cases so they're visible immediately:
--   - partial allocation (request for 15 generators, no single resource has 15)
--   - multi-resource fulfillment (two different owners' generators fill one request)
--   - a resource serving multiple zones (the boat covers two wards)
--   - a flagged duplicate request
--   - a confirmed allocation driving quantity_fulfilled / status automatically
-- Run after schema.sql (or after `alembic upgrade head`). See reset_db.sql.
-- ============================================================================

BEGIN;

-- ---------- Owners ----------
INSERT INTO owners (owner_id, name, owner_type, contact_phone, verification_status) VALUES
    ('a1111111-1111-1111-1111-111111111111', 'State Disaster Response Agency', 'government', '+91-44-1000-0001', 'verified'),
    ('a2222222-2222-2222-2222-222222222222', 'Coastal Relief NGO',              'ngo',        '+91-44-1000-0002', 'verified');

-- ---------- System user (coordinator performing the matches below) ----------
INSERT INTO system_users (user_id, name, role, agency_affiliation) VALUES
    ('b1111111-1111-1111-1111-111111111111', 'Asha Verma', 'coordinator', 'State Disaster Response Agency');

-- ---------- Zones (district > 2 wards) ----------
INSERT INTO zones (zone_id, zone_name, zone_type, parent_zone_id, location, risk_level) VALUES
    ('c1111111-1111-1111-1111-111111111111', 'Kattupalli District',    'district', NULL,
     ST_GeogFromText('SRID=4326;POINT(80.270 13.080)'), 'high'),
    ('c2222222-2222-2222-2222-222222222222', 'Ward 7 - Riverside',     'ward',
     'c1111111-1111-1111-1111-111111111111', ST_GeogFromText('SRID=4326;POINT(80.260 13.090)'), 'critical'),
    ('c3333333-3333-3333-3333-333333333333', 'Ward 8 - Lowlands',      'ward',
     'c1111111-1111-1111-1111-111111111111', ST_GeogFromText('SRID=4326;POINT(80.300 13.070)'), 'high');

-- ---------- Shelter ----------
INSERT INTO shelters (shelter_id, zone_id, name, location, capacity_total) VALUES
    ('d1111111-1111-1111-1111-111111111111', 'c2222222-2222-2222-2222-222222222222',
     'Riverside Community Hall', ST_GeogFromText('SRID=4326;POINT(80.261 13.091)'), 200);

-- ---------- Resources ----------
-- Two generator resources from two different owners, each short of the 15
-- units a single request will need below (edge case: partial + multi-resource).
INSERT INTO resources (resource_id, owner_id, current_zone_id, resource_type, resource_subtype,
                        quantity_total, quantity_available, unit_of_measure, location) VALUES
    ('e1111111-1111-1111-1111-111111111111', 'a1111111-1111-1111-1111-111111111111',
     'c2222222-2222-2222-2222-222222222222', 'generator', '10kVA diesel generator',
     10, 10, 'units', ST_GeogFromText('SRID=4326;POINT(80.259 13.089)')),
    ('e2222222-2222-2222-2222-222222222222', 'a2222222-2222-2222-2222-222222222222',
     'c3333333-3333-3333-3333-333333333333', 'generator', '5kVA diesel generator',
     8, 8, 'units', ST_GeogFromText('SRID=4326;POINT(80.301 13.071)'));

-- A boat whose current zone is Ward 7, but which is registered to also cover
-- Ward 8 (edge case: one resource serving multiple zones).
INSERT INTO resources (resource_id, owner_id, current_zone_id, resource_type, resource_subtype,
                        quantity_total, quantity_available, unit_of_measure, location) VALUES
    ('e3333333-3333-3333-3333-333333333333', 'a1111111-1111-1111-1111-111111111111',
     'c2222222-2222-2222-2222-222222222222', 'boat', '6-seat rescue dinghy',
     3, 3, 'units', ST_GeogFromText('SRID=4326;POINT(80.258 13.088)'));

INSERT INTO resource_zone_coverage (resource_id, zone_id, coverage_priority) VALUES
    ('e3333333-3333-3333-3333-333333333333', 'c2222222-2222-2222-2222-222222222222', 1),
    ('e3333333-3333-3333-3333-333333333333', 'c3333333-3333-3333-3333-333333333333', 2);

-- ---------- Requesters ----------
INSERT INTO requesters (requester_id, name, requester_type, contact_phone, verified_flag) VALUES
    ('f1111111-1111-1111-1111-111111111111', 'Ramesh Kumar', 'shelter_manager', '+91-98-2000-0001', TRUE),
    ('f2222222-2222-2222-2222-222222222222', 'Lakshmi Iyer', 'ngo_field_worker', '+91-98-2000-0002', TRUE);

-- ---------- Emergency Requests ----------
-- Request for 15 generators — exceeds either single resource's quantity, so
-- fulfilling it REQUIRES both partial allocation and multiple resources.
INSERT INTO emergency_requests (request_id, requester_id, zone_id, resource_type_needed,
                                 quantity_requested, urgency_level, location, needed_by) VALUES
    ('11111111-aaaa-1111-1111-111111111111', 'f1111111-1111-1111-1111-111111111111',
     'c2222222-2222-2222-2222-222222222222', 'generator', 15, 'critical',
     ST_GeogFromText('SRID=4326;POINT(80.261 13.091)'), now() + interval '6 hours');

-- A later, smaller generator request from the same requester/zone — flagged as
-- a probable duplicate of the one above, but left independently fulfillable
-- (edge case: duplicate flagging, not auto-merge/auto-cancel).
INSERT INTO emergency_requests (request_id, requester_id, zone_id, resource_type_needed,
                                 quantity_requested, urgency_level, location, duplicate_of_request_id) VALUES
    ('11111111-aaaa-2222-2222-222222222222', 'f1111111-1111-1111-1111-111111111111',
     'c2222222-2222-2222-2222-222222222222', 'generator', 5, 'high',
     ST_GeogFromText('SRID=4326;POINT(80.261 13.091)'), '11111111-aaaa-1111-1111-111111111111');

-- A boat request from Ward 8 — only fulfillable because the boat (homed in
-- Ward 7) is registered to also cover Ward 8 via resource_zone_coverage.
INSERT INTO emergency_requests (request_id, requester_id, zone_id, resource_type_needed,
                                 quantity_requested, urgency_level, location) VALUES
    ('11111111-aaaa-3333-3333-333333333333', 'f2222222-2222-2222-2222-222222222222',
     'c3333333-3333-3333-3333-333333333333', 'boat', 2, 'high',
     ST_GeogFromText('SRID=4326;POINT(80.299 13.069)'));

-- ---------- Allocations ----------
-- Fulfill the 15-generator request with 10 from Owner A's resource...
INSERT INTO allocations (allocation_id, request_id, resource_id, matched_by, quantity_allocated,
                          distance_km, priority_score) VALUES
    ('21111111-bbbb-1111-1111-111111111111', '11111111-aaaa-1111-1111-111111111111',
     'e1111111-1111-1111-1111-111111111111', 'b1111111-1111-1111-1111-111111111111',
     10, 0.3, 95.0);

-- ...and 5 more from Owner B's resource (different owner) — multi-resource fulfillment.
INSERT INTO allocations (allocation_id, request_id, resource_id, matched_by, quantity_allocated,
                          distance_km, priority_score) VALUES
    ('21111111-bbbb-2222-2222-222222222222', '11111111-aaaa-1111-1111-111111111111',
     'e2222222-2222-2222-2222-222222222222', 'b1111111-1111-1111-1111-111111111111',
     5, 14.7, 80.0);

-- Boat allocation for the Ward 8 request, using the boat's cross-zone coverage.
INSERT INTO allocations (allocation_id, request_id, resource_id, matched_by, quantity_allocated,
                          distance_km, priority_score) VALUES
    ('21111111-bbbb-3333-3333-333333333333', '11111111-aaaa-3333-3333-333333333333',
     'e3333333-3333-3333-3333-333333333333', 'b1111111-1111-1111-1111-111111111111',
     2, 4.1, 90.0);

-- ---------- Drive allocations through the lifecycle ----------
-- Owner A's generator allocation goes all the way to confirmed delivery.
UPDATE allocations SET allocation_status = 'dispatched'  WHERE allocation_id = '21111111-bbbb-1111-1111-111111111111';
UPDATE allocations SET allocation_status = 'in_transit'  WHERE allocation_id = '21111111-bbbb-1111-1111-111111111111';
UPDATE allocations SET allocation_status = 'delivered'   WHERE allocation_id = '21111111-bbbb-1111-1111-111111111111';
UPDATE allocations SET allocation_status = 'confirmed'   WHERE allocation_id = '21111111-bbbb-1111-1111-111111111111';

-- Owner B's generator allocation is only dispatched so far — the 15-unit
-- request is therefore still 'partially_fulfilled' (10 of 15) at this point,
-- demonstrating partial allocation mid-flight.
UPDATE allocations SET allocation_status = 'dispatched'  WHERE allocation_id = '21111111-bbbb-2222-2222-222222222222';

-- Boat allocation is fully confirmed — its 2-of-2 request should read 'fulfilled'.
UPDATE allocations SET allocation_status = 'dispatched'  WHERE allocation_id = '21111111-bbbb-3333-3333-333333333333';
UPDATE allocations SET allocation_status = 'in_transit'  WHERE allocation_id = '21111111-bbbb-3333-3333-333333333333';
UPDATE allocations SET allocation_status = 'delivered'   WHERE allocation_id = '21111111-bbbb-3333-3333-333333333333';
UPDATE allocations SET allocation_status = 'confirmed'   WHERE allocation_id = '21111111-bbbb-3333-3333-333333333333';


-- ---------- Demo login accounts (migration 0015 app_users) ----------
-- DEMO ONLY. Every account below uses the documented demo password
-- 'ResQLink-Demo-2026!' (PBKDF2-SHA256, per-account random salt). They log in
-- through the normal POST /api/v1/auth/login path; there is no bypass.
-- Change or deactivate them (UPDATE app_users SET is_active = false) outside demos.
INSERT INTO app_users (user_id, username, password_hash, role, system_user_id, display_name) VALUES
    ('e9000001-0000-4000-8000-000000000001', 'asha.verma', 'pbkdf2_sha256$310000$GH61QYRhr3jR6h7bKjjc-A$YxHprlV-8ZR-rGkSiPMSNrFlz8tH8JSzzW9Ro9-KDRU', 'coordinator', 'b1111111-1111-1111-1111-111111111111', 'Asha Verma');
INSERT INTO app_users (user_id, username, password_hash, role, owner_id, display_name) VALUES
    ('e9000001-0000-4000-8000-000000000002', 'sdra.owner', 'pbkdf2_sha256$310000$_RuLo6pikY3XBa47lCWM0g$qUvsLwzdfGyeLrDCMRXyRD6Y5hK9F85E_oFcHtH1-rM', 'owner', 'a1111111-1111-1111-1111-111111111111', 'State Disaster Response Agency');
INSERT INTO app_users (user_id, username, password_hash, role, owner_id, display_name) VALUES
    ('e9000001-0000-4000-8000-000000000003', 'coastal.owner', 'pbkdf2_sha256$310000$lEa27RsvpdIJaUkT6A5Bzg$w18dDLPqAHoV-eTwhRt4gLRx3ipXntWkpvtEDpNFejI', 'owner', 'a2222222-2222-2222-2222-222222222222', 'Coastal Relief NGO');
INSERT INTO app_users (user_id, username, password_hash, role, requester_id, display_name) VALUES
    ('e9000001-0000-4000-8000-000000000004', 'ramesh.kumar', 'pbkdf2_sha256$310000$BgyN0imfMZo-05v4cH390w$QTc4d2AUifvIUmvXv_B-VYWBmTPvuRrgImGAzBSY2AE', 'requester', 'f1111111-1111-1111-1111-111111111111', 'Ramesh Kumar');
INSERT INTO app_users (user_id, username, password_hash, role, requester_id, display_name) VALUES
    ('e9000001-0000-4000-8000-000000000005', 'lakshmi.iyer', 'pbkdf2_sha256$310000$NFw8txMbw24sv9il1EHaWQ$0q76e5n12GXksMzTbI-txIyE5UPmhqWC8Z4r8hBKJmQ', 'requester', 'f2222222-2222-2222-2222-222222222222', 'Lakshmi Iyer');

COMMIT;

-- ---------- Quick sanity check of the edge cases above ----------
\echo '--- Request fulfillment (expect: 15-generator request = partially_fulfilled, 10/15; boat request = fulfilled, 2/2) ---'
SELECT request_id, resource_type_needed, quantity_requested, quantity_fulfilled, status
FROM emergency_requests
ORDER BY requested_at;

\echo '--- Resource quantity_available after reservations (expect: e1=0, e2=3, e3=1) ---'
SELECT resource_id, resource_subtype, quantity_total, quantity_available, status
FROM resources
ORDER BY resource_id;

\echo '--- Resource zone coverage (expect boat e3 covering both wards) ---'
SELECT resource_id, zone_id, coverage_priority FROM resource_zone_coverage ORDER BY coverage_priority;

\echo '--- Duplicate flag (expect the 5-unit request to point at the 15-unit request) ---'
SELECT request_id, duplicate_of_request_id FROM emergency_requests WHERE duplicate_of_request_id IS NOT NULL;

\echo '--- Audit trail row count per allocation (expect: created + 4 status_changed = 5 rows each for the two fully-confirmed allocations) ---'
SELECT allocation_id, action, performed_at FROM allocation_history WHERE entity_type = 'allocation' ORDER BY allocation_id, performed_at;

\echo '--- Request creation audit rows (expect: one created row per seeded request, written by trg_requests_log_insert) ---'
SELECT entity_id AS request_id, action, remarks FROM allocation_history WHERE entity_type = 'request' ORDER BY performed_at;
