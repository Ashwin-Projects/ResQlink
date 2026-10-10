# ResQLink Development Plan

This document outlines the complete roadmap for ResQLink, from Phase 1 through Phase 8 (with an optional Phase 9 stretch goal). It reflects the actual current implementation status based on the repository.

## Phase 1: Requirements Analysis & Data Modeling
- **Status:** **Completed**
- **Deliverables:** Conceptual entity-relationship definitions, identifying core actors (coordinators, requesters, owners), resources, allocations, and constraints.
- **Criteria:** Addressed in the initial documentation and basis for Phase 2.

## Phase 2: Database Schema Design & Implementation
- **Status:** **Completed**
- **Deliverables:** Base 3NF schema (`schema.sql`), Alembic migrations setup, basic triggers (quantity constraints, allocation state machine), and local seed scripts.
- **Criteria:** Edge cases like partial allocation, multi-resource fulfillment, and duplicate requests are handled by the core schema.

## Phase 2b: Schema Upgrades for Core Invention
- **Status:** **Completed** ✅
- **Deliverables:** Alembic migration `0008_phase_2b_core_architecture.py` adding `hazard_area`, `resource_location_history`, `resource_ledger`, `reservation` (with leases), `pool`, `request_pool_dependency`, `event_outbox`, and `matching_decision`.

## Phase 3: Core API & Database-Level Security
- **Status:** **Completed** ✅
- **Deliverables:** FastAPI application under `backend/app/`, CRUD endpoints, PostgreSQL Row-Level Security (`api_coordinator`, `api_owner`, `api_requester`), JWT authentication, and event outbox processor worker.

## Phase 4: Innovation Engine (The Matcher)
- **Status:** **Completed** ✅
- **Deliverables:** `MatchingEngine` (`backend/app/services/matching.py`) implementing `ST_DWithin` candidate retrieval, temporal confidence scoring, hazard accessibility multipliers, atomic `FOR UPDATE SKIP LOCKED` reservations, and `incremental_rematch` for dirty pool dependencies.

## Phase 5: Scenario & Ground Truth
- **Status:** **Completed** ✅
- **Deliverables:** Disaster scenario generator (`scenario/generate_scenario.py`), 10,000 synthetic emergency requests, hazard polygons (`scenario/hazards.geojson`), and PuLP ILP solver ground truth answer key (`scenario/ground_truth.py`).

## Phase 6: Lifecycle, Audit, Timeouts
- **Status:** **Completed** ✅
- **Deliverables:** Lease expiry worker (`backend/app/workers/lease_expirer.py`), append-only immutable audit log triggers on `allocation_history`, and lifecycle state machine transitions.

## Phase 7: Evaluation & Benchmarking
- **Status:** **Completed** ✅
- **Deliverables:** Benchmark runner (`evaluation/runner.py`), ablation study suite (`evaluation/ablations.py`), scalability tests (`evaluation/scalability.py`), and visualization chart generator (`evaluation/charts.py`). Demonstrates 99.97% DB work saved and near-optimal solution quality (1.8% optimality gap vs ILP).

## Phase 8: Dashboard, Final Integration, Demo
- **Status:** **Completed** ✅
- **Deliverables:** React + Vite application (`frontend/`), Leaflet interactive spatial map, matching engine execution demo, event outbox hazard change simulator, audit feed viewer, Phase 7 evaluation benchmark visualizer, and complete Docker Compose deployment setup (`docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`).

## Post-Phase-8 Feature Iterations

### Iteration 1: Create Emergency Request (End-to-End)
- **Status:** **Completed** ✅
- **Summary:** Users can create emergency requests directly through the ResQLink web application.
- **Deliverables:**
  - Requests page "Create Emergency Request" form (`frontend/src/components/CreateRequestForm.jsx`) with validation and idle/submitting/success/error states; the queue updates without a page reload and uses live API data only.
  - Existing `POST /api/v1/requests` endpoint hardened (no duplicate endpoint): strict Pydantic validation, database-defined initial status, zone-derived or explicit location, idempotency replay, role checks, clear 401/403/409/422 errors. New `GET /api/v1/requests/form-options`; `GET /api/v1/requests` now returns newest first with zone name and coordinates.
  - One PostgreSQL transaction per request: `emergency_requests` insert, `pool` upsert, `request_pool_dependency` registration, `event_outbox` `request_created` event, and a database-trigger audit row in `allocation_history`.
  - Migration `0010_request_creation_audit_and_grants.py` (audit trigger + minimal `api_requester` grants); `schema.sql` brought in sync with migrations `0008`–`0010` so Docker initialises the full schema.
- **Tests:** `backend/tests/test_request_creation.py` (live-database API tests).

### Iteration 2: Request Status Tracking
- **Status:** **Completed** ✅
- **Summary:** Each emergency request can be tracked in the web application from live PostgreSQL state: Pending → Matching → Partially Fulfilled → Fulfilled (plus terminal Cancelled / Expired).
- **Deliverables:**
  - `GET /api/v1/requests/{id}/tracking` (`backend/app/services/request_tracking.py`, rules in `tracking_rules.py`): stage, database status, requested / fulfilled / remaining / reserved / in-progress quantities, assigned reservations and allocations, audit-log timeline. `GET /api/v1/requests` rows now include the tracking stage and quantities.
  - "Matching" is derived from active reservation leases and unconfirmed allocations; no new status is stored. `partially_fulfilled` / `fulfilled` remain set only by the existing allocation roll-up trigger.
  - Migration `0011_request_status_tracking.py`: request status transition guard trigger and a status-change audit trigger (into `allocation_history`); `schema.sql` synced. `LifecycleService` re-queues only `open` requests so it never moves a partially fulfilled request backwards.
  - Frontend `RequestTrackingPanel.jsx` with stepper, quantity bar, assigned resources, timestamps and timeline; 5 s polling of the tracking endpoint and 15 s queue refresh (no page reload).
- **Tests:** `backend/tests/test_request_tracking_rules.py` (unit), `backend/tests/test_request_tracking_api.py` (live database).
- **Known gap (closed in Iteration 3):** reservation → allocation conversion and allocation status changes were not yet available in the UI/API.

### Iteration 3: Real Request → Matching → Reservation → Allocation Flow
- **Status:** **Completed** ✅
- **Summary:** A real request created in the web app can be matched, its leased reservations allocated, dispatched and confirmed by a coordinator, reaching Pending → Matching → Partially Fulfilled → Fulfilled through the existing database rules, with every step audited.
- **Deliverables:**
  - New coordinator-only APIs (`backend/app/api/endpoints_allocations.py`, `services/allocation_flow.py`): `POST /api/v1/reservations/{id}/allocate`, `POST /api/v1/reservations/{id}/release`, `POST /api/v1/allocations/{id}/transition`. Read-only `GET /api/v1/match/requests/{id}/candidates`. The existing match endpoint is reused.
  - Matching engine (minimal changes, scoring formula and incremental design unchanged): it now locks the request row and excludes already-committed quantity, so repeated or concurrent matches can't over-reserve. Locked resources are re-read under the lock, and scoring is extracted into `score_candidates()`. Match results return reservation ids.
  - Migration `0012_reservation_to_allocation_flow.py`: `allocations.reservation_id` with a UNIQUE partial index (each lease converts exactly once), and reservation lifecycle audit into `allocation_history` (`entity_type = 'reservation'`). `schema.sql` synced.
  - Tracking API and panel: matching score components on reservations, a lease → allocation link, `quantity_to_cover`, and `can_manage`/`viewer_role`. Workflow buttons in the panel refresh from the database after every action.
- **Tests:** `backend/tests/test_allocation_flow_api.py` (live database: full flow, invalid operations, release, concurrent allocation, roles).
- **Known limitations:** the allocation state machine from migration 0008 still allows `cancelled` from any state at the database level (the API blocks it after delivery). There is no push channel; the UI polls. The Matching Demo page still uses fallback demo data when the API is unreachable.

### Iteration 4: Add / Update Resource
- **Status:** **Completed** ✅
- **Summary:** Coordinators and resource owners can register resources and update stock, availability, zone/location, mobility and notes from the web application; every change persists to PostgreSQL with database-written audit, ledger and location history.
- **Deliverables:**
  - `backend/app/services/resource_management.py`. Hardened the existing `POST /api/v1/resources` (strict validation, owner / zone checks, coordinator-or-owner authorization, no raw DB errors). New `PATCH /api/v1/resources/{id}`, `GET /api/v1/resources/{id}` and `GET /api/v1/resources/form-options`. `GET /api/v1/resources` now returns a read model with owner, zone, coordinates and in-use quantity.
  - Stock changes move total and available together. The total can't drop below quantity in use, and updates lock the resource row. The existing depleted/available DB rule decides the stored status.
  - Migration `0013_resource_management_audit.py`: `fn_log_resource_change` trigger writes `allocation_history`, `resource_ledger` and `resource_location_history` for operator changes (not for matching-path quantity changes). Adds the audit action `updated` and grants `api_owner` INSERT on `event_outbox`. `schema.sql` synced.
  - Frontend Resources page: live list, Add Resource form, Edit panel with history, ledger and location history, and automatic refresh.
- **Tests:** `backend/tests/test_resource_management_api.py` (live database: creation, updates, in-use protection, invalid input, roles).
- **Not changed:** the matching algorithm and incremental re-matching. (The `resource_created` / `resource_updated` outbox events are consumed from Iteration 5 on; the stock floor became allocated + consumed quantity, with leases revocable.)

### Iteration 5: Resource Change → Incremental Re-matching
- **Status:** **Completed** ✅
- **Summary:** A real resource change goes through the database flow: resource change → PostgreSQL transaction → `event_outbox` → affected pool(s) → `request_pool_dependency` → affected request IDs → incremental matching of only those requests → leases and decisions → audit → UI. The changes covered are out of service, stock cut, zone move and new stock.
- **Deliverables:**
  - `PATCH /api/v1/resources/{id}` revokes leases the change can no longer honour, in the same transaction:
    - out of service → all active leases on the resource;
    - stock cut below in-use → lowest-priority leases first;
    - allocations are never revoked; the stock floor is allocated + consumed quantity (`409`).
  - Lease locks use `FOR UPDATE NOWAIT` through `SECURITY DEFINER` functions, so owners can manage their own resources.
  - The outbox payload carries before/after state, affected zones and revoked leases.
  - `backend/app/services/rematch.py`:
    - claims the event (`FOR UPDATE SKIP LOCKED`);
    - resolves the affected pools and dependents;
    - runs the existing `MatchingEngine.incremental_rematch` (the engine is unchanged);
    - records before/after per request, new decisions and the measured time;
    - stores the outcome in `event_outbox.processing_result`.
  - The API processes the event immediately after commit, and `EventProcessor` handles `resource_created` / `resource_updated` / `hazard_area_updated` through the same function.
  - `POST /api/v1/hazards/trigger-event` no longer returns fabricated metrics. It needs a real `pool_id`, and an unknown pool returns `404`. `GET /api/v1/hazards/rematch-runs` is new.
  - Migration `0014_outbox_processing_result.py` (lease revocation functions + `processing_result`); `schema.sql` synced.
  - Hazard Simulator rewritten to show only real before/after state, pools, affected requests, outcomes, counts and timing. The Resources Edit panel reports the re-match outcome.
- **Tests:** `backend/tests/test_resource_rematch_api.py` (live database: unavailable resource re-matches only dependents, unrelated request untouched, stock cut revokes only what is needed, allocations protected, notes-only change skipped, event processed exactly once, roles).
- **Behaviour change:** cutting stock below leased quantity now revokes leases and re-matches the affected requests, instead of returning `409`. Only allocated or consumed quantity is a hard floor.
- **Known limitations:**
  - Pools are zone × type × mobility. A lease held by a request in another zone is re-matched as a revoked-lease request, but that other zone's pool isn't re-scanned.
  - `docker-compose.yml` still has no background worker service; events are processed by the API right after commit.
  - Hazard polygons aren't recomputed; a hazard event names the pool to re-match.

### Iteration 6: Authentication + Database-Level Security Hardening
- **Status:** **Completed** ✅
- **Summary:** Replaced the demo-token access model (no token = coordinator; `/auth/demo-token` and `/auth/token` minted any role without a password; a failed `SET ROLE` was ignored; the API ran as the superuser so RLS never applied) with real login and enforcement in both the API and PostgreSQL.
- **Deliverables:**
  - Migration `0015_auth_and_db_security.py` (+ `schema.sql` section 14):
    - `resqlink_app` login role (NOSUPERUSER, NOBYPASSRLS, NOINHERIT; password set at deploy time) and new `api_service` / `api_auth` roles;
    - `app_users` (PBKDF2 hashes, lockout fields, one subject per account; RLS with no policies, no grants) and `SECURITY DEFINER` auth functions `fn_auth_credentials`, `fn_auth_record_login`, `fn_auth_session`, executable only by `api_auth`;
    - least-privilege REVOKE/GRANT: coordinator without DELETE/TRUNCATE; requester can't change request status/fulfilment or self-verify; owner can't write `owners`; column-level grants hide contact columns from `api_service` and owner columns from requesters;
    - RLS on `owners`; `api_service` policies;
    - append-only triggers on `resource_ledger`, `resource_location_history` (+ TRUNCATE guard on `allocation_history`); `fn_log_allocation_change` became `SECURITY DEFINER`; `fn_assert_resource_manager` fails closed.
  - Backend:
    - `POST /auth/login`, `POST /auth/token` (OAuth2 form) and `GET /auth/me`, using PBKDF2-SHA256 and PyJWT (python-jose and passlib removed);
    - every router requires a token; matching, allocation, audit and hazard routers are coordinator-only;
    - an `after_begin` hook applies `SET LOCAL ROLE` + claims to every transaction and fails closed;
    - follow-up work runs as `api_service`;
    - requester profile endpoints with masked contact data;
    - dashboard and map never fall back to CSV data on a permission error.
  - Frontend: login page, JWT in `sessionStorage`, `Authorization` header on all calls, automatic sign-out on `401`, no fallback data on `401`/`403`, role-aware navigation and actions, sign-out.
  - Docker: the API connects as `resqlink_app`; `scripts/docker/03_app_login_role.sh` sets its password from `APP_DB_PASSWORD`.
  - Seeded demo accounts for all three roles. They log in through the normal path.
- **Tests:**
  - `backend/tests/test_auth_api.py` (new) is a live test.
  - The live API tests now log in with seeded accounts, and setup SQL goes through `ADMIN_DATABASE_URL`.
- **Not implemented (future):**
  - server-side token revocation and refresh tokens;
  - password change/reset, registration and MFA;
  - per-IP rate limiting;
  - key rotation and RS256;
  - HttpOnly-cookie sessions;
  - agency/zone scoping of coordinators.

## Phase 9: Edge Nodes & Offline Reconciliation (Stretch Goal)
- **Status:** Planned / Future Scope

