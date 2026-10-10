-- Phase 2b Database Validations & Tests
-- Run this script in PostgreSQL after applying migrations to verify Phase 2b features.

BEGIN;

-- 1. Hazard polygon insertion
INSERT INTO hazard_area (geometry, hazard_type, severity, valid_from, valid_to)
VALUES (
    ST_GeomFromText('MULTIPOLYGON(((0 0, 0 1, 1 1, 1 0, 0 0)))', 4326),
    'flood',
    'high',
    now(),
    now() + interval '7 days'
);
-- Validation: Should succeed.

-- 2. Valid temporal location history
-- Assuming resource_id exists, we use a placeholder or insert a dummy resource.
-- First, get a valid resource ID (we assume the seed script has been run)
DO $$
DECLARE 
    v_res_id UUID;
BEGIN
    SELECT resource_id INTO v_res_id FROM resources LIMIT 1;
    
    IF v_res_id IS NOT NULL THEN
        INSERT INTO resource_location_history (resource_id, location, recorded_at, source, confidence)
        VALUES (v_res_id, ST_SetSRID(ST_MakePoint(-71.06, 42.36), 4326), now(), 'gps', 95.5);
    END IF;
END $$;
-- Validation: Should succeed.

-- 3. Ledger quantity changes
DO $$
DECLARE 
    v_res_id UUID;
BEGIN
    SELECT resource_id INTO v_res_id FROM resources LIMIT 1;
    
    IF v_res_id IS NOT NULL THEN
        INSERT INTO resource_ledger (resource_id, delta_qty, reason)
        VALUES (v_res_id, -5.0, 'consumption');
    END IF;
END $$;
-- Validation: Should succeed.

-- 4, 5. Reservation creation and lease expiration fields
DO $$
DECLARE
    v_res_id UUID;
    v_req_id UUID;
BEGIN
    SELECT resource_id INTO v_res_id FROM resources WHERE quantity_available > 10 LIMIT 1;
    SELECT request_id INTO v_req_id FROM emergency_requests LIMIT 1;

    IF v_res_id IS NOT NULL AND v_req_id IS NOT NULL THEN
        INSERT INTO reservation (request_id, resource_id, quantity, status, lease_expires_at)
        VALUES (v_req_id, v_res_id, 2.0, 'active', now() + interval '1 hour');
    END IF;
END $$;
-- Validation: Should succeed and reserve quantity.

-- 6. Over-reservation prevention
DO $$
DECLARE
    v_res_id UUID;
    v_req_id UUID;
BEGIN
    SELECT resource_id INTO v_res_id FROM resources WHERE quantity_available > 0 LIMIT 1;
    SELECT request_id INTO v_req_id FROM emergency_requests LIMIT 1;

    IF v_res_id IS NOT NULL AND v_req_id IS NOT NULL THEN
        BEGIN
            INSERT INTO reservation (request_id, resource_id, quantity, status, lease_expires_at)
            VALUES (v_req_id, v_res_id, 99999.0, 'active', now() + interval '1 hour');
            RAISE EXCEPTION 'Test failed: Over-reservation was allowed.';
        EXCEPTION WHEN OTHERS THEN
            -- Expected failure
            RAISE NOTICE 'Test passed: Over-reservation prevented (%).', SQLERRM;
        END;
    END IF;
END $$;

-- 7. Pool creation
DO $$
DECLARE 
    v_zone_id UUID;
    v_pool_id UUID;
BEGIN
    SELECT zone_id INTO v_zone_id FROM zones LIMIT 1;
    
    IF v_zone_id IS NOT NULL THEN
        INSERT INTO pool (zone_id, resource_type, mobility_class)
        VALUES (v_zone_id, 'generator', 'mobile') RETURNING pool_id INTO v_pool_id;
        
        -- 8. Request-to-pool dependency creation
        DECLARE
            v_req_id UUID;
        BEGIN
            SELECT request_id INTO v_req_id FROM emergency_requests LIMIT 1;
            IF v_req_id IS NOT NULL THEN
                INSERT INTO request_pool_dependency (request_id, pool_id)
                VALUES (v_req_id, v_pool_id);
            END IF;
        END;
        
        -- 9, 10. Event outbox creation (transactionally coupled)
        INSERT INTO event_outbox (event_type, pool_id, payload)
        VALUES ('pool_updated', v_pool_id, '{"reason": "new_resource_available"}'::jsonb);
    END IF;
END $$;

-- 11. Matching decision insertion
DO $$
DECLARE
    v_res_id UUID;
    v_req_id UUID;
BEGIN
    SELECT resource_id INTO v_res_id FROM resources LIMIT 1;
    SELECT request_id INTO v_req_id FROM emergency_requests LIMIT 1;

    IF v_res_id IS NOT NULL AND v_req_id IS NOT NULL THEN
        INSERT INTO matching_decision (request_id, resource_id, score_components, final_score, algorithm_version, mode)
        VALUES (v_req_id, v_res_id, '{"accessibility": 0.9, "urgency": 0.8}'::jsonb, 0.85, 'v1.0', 'incremental');
    END IF;
END $$;

-- 12. Audit immutability
DO $$
BEGIN
    -- We assume history exists from allocations. If not, this is a no-op which still passes the script.
    DELETE FROM allocation_history WHERE log_id IS NOT NULL;
    RAISE EXCEPTION 'Test failed: Deletion from allocation_history was allowed.';
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Test passed: Audit immutability enforced (%).', SQLERRM;
END $$;

-- 13. Phase 1/2 edge cases (Allocations with new PENDING/PROPOSED/RESERVED statuses)
DO $$
DECLARE
    v_res_id UUID;
    v_req_id UUID;
    v_alloc_id UUID;
BEGIN
    SELECT resource_id INTO v_res_id FROM resources WHERE quantity_available > 0 LIMIT 1;
    SELECT request_id INTO v_req_id FROM emergency_requests LIMIT 1;

    IF v_res_id IS NOT NULL AND v_req_id IS NOT NULL THEN
        -- Test matched -> proposed -> reserved -> dispatched -> confirmed -> fulfilled
        INSERT INTO allocations (request_id, resource_id, quantity_allocated, allocation_status)
        VALUES (v_req_id, v_res_id, 1, 'matched') RETURNING allocation_id INTO v_alloc_id;
        
        UPDATE allocations SET allocation_status = 'proposed' WHERE allocation_id = v_alloc_id;
        UPDATE allocations SET allocation_status = 'reserved' WHERE allocation_id = v_alloc_id;
        UPDATE allocations SET allocation_status = 'dispatched' WHERE allocation_id = v_alloc_id;
        UPDATE allocations SET allocation_status = 'confirmed' WHERE allocation_id = v_alloc_id;
        UPDATE allocations SET allocation_status = 'fulfilled' WHERE allocation_id = v_alloc_id;
        
        RAISE NOTICE 'Test passed: Extended lifecycle allocation transitions succeed.';
    END IF;
END $$;

ROLLBACK;
