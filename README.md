# ResQLink

### Emergency Resource Coordination for Flood and Cyclone Response

ResQLink is a database-driven emergency resource coordination system designed to support disaster-response operations during events such as floods and cyclones.

The platform centralizes emergency resources, requests, shelters, hazard information, and allocation state in a PostgreSQL/PostGIS-based system. It provides real-time visibility of available resources and supports intelligent matching between emergency requests and suitable resources.

The core technical contribution is:

> **Dependency-Tracked Incremental Re-Matching with Contention-Safe Leased Reservation**

Rather than repeatedly evaluating the entire resource-request space whenever availability changes, ResQLink maintains dependencies between requests and resource pools and re-evaluates only the affected request set. Reservations are protected through transactional, lease-based allocation to prevent concurrent double allocation.

---

## Project Status

| Phase | Description | Status |
|---|---|---|
| Phase 1 | Data Modeling and Requirements | Completed |
| Phase 2 | Base Schema and Migrations | Completed |
| Phase 2b | Core Architecture for Incremental Matching | Completed |
| Phase 3 | Core API and Security | Completed |
| Phase 4 | Matching Engine | Completed |
| Phase 5 | Disaster Scenario and Ground Truth | Completed |
| Phase 6 | Lifecycle, Audit and Timeouts | Completed |
| Phase 7 | Evaluation and Benchmarking | Completed |
| Phase 8 | Dashboard, Integration and Deployment | Completed |

### Post-Phase-8 Feature Iterations

| Feature | Description | Status |
|---|---|---|
| Create Emergency Request | Users can create emergency requests directly through the ResQLink web application (React form → FastAPI → PostgreSQL) | Implemented |
| Request Status Tracking | Track each request (Pending → Matching → Partially Fulfilled → Fulfilled) from live PostgreSQL state, with quantities, assigned resources and a timestamped timeline | Implemented |
| Resource Change → Incremental Re-matching | A real resource change (out of service, stock cut, zone move, new stock) revokes leases it can no longer honour, writes an outbox event, and re-matches only the requests that depend on the affected pool(s); the Hazard Simulator shows the stored outcome | Implemented |
| Add / Update Resource | Register resources and update stock, availability, zone/location, mobility and notes from the web app, with database-written ledger, location history and audit | Implemented |
| Request → Match → Reserve → Allocate → Confirm | Coordinators match a real request, convert leased reservations into allocations, dispatch and confirm them, and the database updates fulfilment — all from the web application, fully audited | Implemented |
| Authentication + Database-Level Security | Real login (PBKDF2 + signed JWT), role-aware UI, coordinator / owner / requester rules enforced by the API **and** by PostgreSQL (unprivileged login role, per-transaction `SET LOCAL ROLE`, least-privilege GRANT/REVOKE, RLS policies, private requester contact data) — migration `0015` | Implemented |

---

## Key Capabilities

- Centralized management of emergency resources and requests
- Web-based emergency request submission persisted to PostgreSQL
- Live request status tracking backed by the database lifecycle
- End-to-end match → reserve → allocate → confirm workflow in the web application
- Resource registration and updates with an append-only stock ledger and location history
- PostgreSQL and PostGIS spatial data management
- Hazard-aware resource accessibility
- Temporal confidence for changing resource availability
- Dependency-tracked incremental re-matching
- Contention-safe leased reservations
- Event-driven resource state updates
- Emergency request prioritization
- Lifecycle and reservation management
- Immutable audit history
- Interactive disaster-response map
- Scenario generation and ILP-based ground truth
- Benchmarking and ablation analysis
- React-based operational dashboard
- Docker-based deployment architecture

---

## Core Innovation

Traditional resource allocation systems commonly perform matching through approaches such as nearest-resource selection or repeated full scans of available inventory.

These approaches become increasingly expensive when:

- resource availability changes frequently,
- requests remain dependent on shared resource pools,
- hazard conditions change dynamically,
- multiple requests compete for the same resources,
- and concurrent operators attempt allocation simultaneously.

ResQLink addresses this using a database-native incremental matching architecture.

### Dependency-Tracked Incremental Re-Matching

The system maintains a dependency mapping between pending requests and resource pools represented by combinations such as:

```text
Zone × Resource Type × Mobility Class
```

When a resource or relevant operational state changes:

1. A state-change event is recorded.
2. The affected resource pool is identified.
3. The dependency index identifies requests associated with that pool.
4. Only those dependent requests are re-evaluated.
5. Matching decisions are stored.
6. Candidate resources are reserved transactionally using lease-based locking.

This avoids unnecessary full-system re-computation.

### Supporting Mechanisms

**Temporal Confidence**

Resource availability can become less reliable over time. ResQLink incorporates confidence decay into effective resource capacity.

```text
Effective Capacity = Quantity × Confidence
```

**Hazard-Aware Accessibility**

Matching is not based only on straight-line distance. Accessibility is adjusted using hazard information and mobility characteristics so that geographically close resources are not automatically treated as operationally reachable.

**Contention-Safe Reservation**

Reservations use transactional locking and lease expiration to prevent multiple concurrent requests from allocating the same resource.

---

## System Architecture

```text
┌───────────────────────────────┐
│       React + Vite UI         │
│    Leaflet Spatial Dashboard   │
└───────────────┬───────────────┘
                │ REST API
                ▼
┌───────────────────────────────┐
│          FastAPI API          │
│                               │
│  Authentication               │
│  Resource / Request APIs      │
│  Matching Engine              │
│  Lifecycle Services           │
│  Audit Services               │
│  Event Processing             │
└───────────────┬───────────────┘
                │
                ▼
┌───────────────────────────────┐
│      PostgreSQL + PostGIS     │
│                               │
│  Resources                    │
│  Requests                     │
│  Pools                        │
│  Dependencies                 │
│  Reservations                 │
│  Matching Decisions           │
│  Hazard Geometry              │
│  Event Outbox                 │
│  Audit History                │
└───────────────────────────────┘
```

---

## Technology Stack

### Backend

- Python
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic
- JWT authentication
- PostgreSQL
- PostGIS

### Frontend

- React
- Vite
- JavaScript
- Leaflet
- Lucide React

### Evaluation

- Python
- PuLP
- CBC
- Synthetic disaster scenarios
- Multi-seed evaluation
- Baseline and ablation experiments

### Deployment

- Docker
- Docker Compose
- PostgreSQL/PostGIS container
- FastAPI container
- React frontend container

---

## Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── endpoints.py
│   │   │   ├── endpoints_auth.py
│   │   │   ├── endpoints_dashboard.py
│   │   │   ├── endpoints_evaluation.py
│   │   │   ├── endpoints_hazards.py
│   │   │   ├── endpoints_map.py
│   │   │   ├── endpoints_matching.py
│   │   │   └── endpoints_audit.py
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── security/
│   │   ├── services/
│   │   └── workers/
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   │   ├── DashboardView.jsx
│   │   │   ├── ResourceView.jsx
│   │   │   ├── RequestView.jsx
│   │   │   ├── MatchingDemoView.jsx
│   │   │   ├── MapView.jsx
│   │   │   ├── HazardDemoView.jsx
│   │   │   ├── AuditView.jsx
│   │   │   └── EvaluationView.jsx
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── Dockerfile
│   ├── package.json
│   └── README.md
│
├── migrations/
│   ├── versions/
│   │   ├── 0001_*.py
│   │   ├── 0002_*.py
│   │   ├── ...
│   │   ├── 0008_phase_2b_core_architecture.py
│   │   ├── 0009_phase_3_rls_security.py
│   │   ├── 0010_request_creation_audit_and_grants.py
│   │   ├── 0011_request_status_tracking.py
│   │   ├── 0012_reservation_to_allocation_flow.py
│   │   ├── 0013_resource_management_audit.py
│   │   └── 0014_outbox_processing_result.py
│   ├── alembic.ini
│   └── env.py
│
├── scenario/
│   ├── generate_scenario.py
│   ├── generate_scale_data.py
│   ├── generate_hazard_events.py
│   ├── ground_truth.py
│   ├── ground_truth.json
│   ├── requests.csv
│   ├── resources.csv
│   ├── hazards.geojson
│   └── ...
│
├── evaluation/
│   ├── adapter.py
│   ├── runner.py
│   ├── baselines.py
│   ├── ablations.py
│   ├── metrics.py
│   ├── scalability.py
│   ├── concurrency.py
│   └── results/
│
├── docker-compose.yml
├── schema.sql
├── scripts/
├── CLAUDE.md
├── DEVELOPMENT_PLAN.md
├── PROJECT_OVERVIEW.md
├── DBTHON_CHALLENGE.md
└── NOVELTY_AND_PATENT_STRATEGY.md
```

---

## Database Design

ResQLink uses PostgreSQL with PostGIS for transactional and spatial data management.

The schema includes entities for:

- Owners
- Requesters
- Resources
- Resource location history
- Resource ledger
- Requests
- Allocations
- Reservations
- Shelters
- Zones
- Hazard areas
- Resource pools
- Request-pool dependencies
- Matching decisions
- Event outbox
- Audit history

The database also uses:

- foreign-key constraints
- check constraints
- spatial indexes
- transactional locking
- row-level security
- lifecycle/state validation
- audit mechanisms
- indexed lookup paths
- lease expiration

---

## Matching Workflow

A simplified request-processing flow is:

```text
Emergency Request
       │
       ▼
Request Classification
       │
       ▼
Identify Relevant Resource Pools
       │
       ▼
Retrieve Candidate Resources
       │
       ├── Spatial Accessibility
       ├── Resource Type
       ├── Mobility Class
       ├── Quantity
       ├── Temporal Confidence
       └── Request Urgency
       │
       ▼
Rank Matching Candidates
       │
       ▼
Transactional Reservation
       │
       ▼
Matching Decision
       │
       ▼
Audit / Lifecycle Update
```

When resource availability changes, the incremental engine uses the dependency index to determine which pending requests must be reconsidered.

---

## Frontend

The Phase 8 dashboard provides an operational interface for demonstrating the system.

### Dashboard

Displays:

- overall system status
- resource counts
- request queue metrics
- urgent requests
- active reservations
- allocation state
- matching indicators

### Resource View

Live resource inventory from `GET /api/v1/resources` (no fallback data; refreshes every 15 s) showing type, subtype, owner, available / total / in-use quantity, mobility class, status, zone and coordinates, and last verification time.

#### Add / Update Resource

Coordinators (any owner) and resource owners (their own resources only) can:

- **Add Resource:** owner, type, subtype, total quantity (optionally less available now), unit, zone (optional exact coordinates, otherwise the zone point), availability, mobility class and condition notes.
- **Update** a resource from its **Edit** panel:
  - total stock;
  - availability (`available`, `maintenance`, `unavailable`);
  - zone and/or exact location;
  - mobility class;
  - subtype and notes.

The panel also shows the resource's audit history, stock ledger and location history read from the database.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/resources/form-options` | Owners (an owner sees only itself), zones and allowed values; `can_manage` |
| `POST /api/v1/resources` | Create (existing endpoint, hardened). `201`; `401` invalid token, `403` requester / owner registering for someone else, `422` validation |
| `GET /api/v1/resources` | List visible to the caller's RLS role, most recently updated first |
| `GET /api/v1/resources/{id}` | Resource + ledger + location history + audit history + currently leased / allocated quantity |
| `PATCH /api/v1/resources/{id}` | Update only the fields sent; returns `before` / `after` state, `revoked_leases` and the incremental re-match outcome (`rematch`). `404` if not visible (RLS), `409` if stock would drop below allocated + consumed quantity or a lease is being converted concurrently, `422` invalid / no change |

Rules:

- **Quantities in use:** "in use" is total minus available (leased, allocated or consumed). A stock change of ±N moves both total and available by N.
  - **Leases can be revoked:** cutting stock below what is in use revokes active leases (lowest priority first, then newest) until the new total fits. Taking a resource to `maintenance` / `unavailable` revokes all of its active leases.
  - **Allocations cannot:** allocations and consumed quantity are never revoked; the total can't go below them (`409`).
  - **Locking:** the update locks the resource row (`FOR UPDATE`) and its leases (`FOR UPDATE NOWAIT`, through the `SECURITY DEFINER` functions from migration `0014`), so it serializes with the matching engine and fails fast instead of deadlocking with a concurrent allocation.
- **Database status rules win:** `depleted` is derived by the existing `fn_resources_sync_status` trigger. The API only accepts `available`, `maintenance` and `unavailable`, and setting `available` on a resource with no free stock is stored as `depleted`.
- **History is written by the database:** trigger `fn_log_resource_change` (migration `0013`) writes, in the same transaction, `allocation_history` (`created`, `status_changed`, `quantity_updated`, `updated`, with only the changed fields), `resource_ledger` (`initial_stock` and `stock_adjustment`) and `resource_location_history`. It doesn't fire on the matching path's own quantity changes. Each API change also emits a `resource_created` / `resource_updated` outbox event.
- **Authorization:** coordinator for any resource; owner for its own (PostgreSQL RLS `owner_resource_policy`); requester read-only. An operator update refreshes `last_verified_at`.

Tables affected: `resources`, `resource_ledger`, `resource_location_history`, `allocation_history`, `event_outbox` (read: `owners`, `zones`, `reservation`, `allocations`).

### Request View

Contains the **Create Emergency Request** form and the live request queue.

Users can create emergency requests directly through the ResQLink web application. The form collects:

- requester (from the `requesters` table)
- resource type (values mirror the `emergency_requests` CHECK constraint)
- quantity required (`> 0`, max 2 decimal places — `NUMERIC(10,2)`)
- urgency (`critical`, `high`, `medium`, `low`)
- zone / location (from the `zones` table; optional precise latitude/longitude, otherwise the zone's point is used)
- mobility / accessibility requirement (`any`, `land`, `boat`, `amphibious`, `air`)
- optional needed-by time and description (≤ 1000 characters)

The form validates input client-side, shows idle / submitting / success / error states, disables submission while a request is in flight, and sends an idempotency key so a retried submission never creates a duplicate row. On success the created request returned by the API (request ID, resource type, quantity, urgency, zone, database-defined initial status) is shown and inserted at the top of the queue without a page reload.

The queue is loaded from `GET /api/v1/requests` (newest first) and displays:

- request identifiers
- requested quantity and fulfillment progress
- urgency
- zone
- lifecycle state
- matching controls

The Requests page does not use fallback/demo data: if the API is unreachable it shows an error state with a retry button.

#### Create Emergency Request — end-to-end flow

```text
React form (CreateRequestForm.jsx)
  → POST /api/v1/requests                       (FastAPI, Pydantic validation, JWT role)
  → get_db_with_rls: SET LOCAL ROLE api_<role>  (PostgreSQL RLS + grants enforced)
  → one PostgreSQL transaction:
       INSERT emergency_requests                (status = column default 'open')
         ↳ trg_requests_log_insert → allocation_history 'request/created' audit row
       UPSERT pool (zone × resource_type × mobility_class)
       INSERT request_pool_dependency           (pool-dependency index)
       INSERT event_outbox 'request_created'    (transactional outbox, carries pool_id)
  → 201 Created + created request
  → Requests page updates in place
  → request is available to /api/v1/match/requests/{id}/match and
    /api/v1/match/engine/incremental/{pool_id}
```

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/requests` | Create a request. `201` = created, `200` = idempotent replay (same `idempotency_key`), `401` invalid token, `403` role not permitted, `409` conflict, `422` validation error |
| `GET /api/v1/requests?skip=&limit=` | List requests visible to the caller's role (newest first, `limit` ≤ 500) |
| `GET /api/v1/requests/form-options` | Requesters, zones, resource types, urgency levels and mobility classes for the form |

#### Request Status Tracking

Each request in the queue has a **Track** button (a newly created request is tracked automatically). The tracking panel shows:

- the tracking stage and the underlying database status
- a stepper: **Pending → Matching → Partially Fulfilled → Fulfilled** (plus terminal *Cancelled* / *Expired*)
- requested, fulfilled and remaining quantity, plus quantity currently reserved (active leases) and allocated (not yet confirmed)
- assigned resources: leased reservations (resource, owner, quantity, lease expiry, lease state) and allocations (status, matched / dispatched / confirmed times)
- timestamps (requested, needed-by, last change) and a timeline built from the append-only `allocation_history` audit log

The panel re-reads `GET /api/v1/requests/{id}/tracking` every 5 seconds (paused while the browser tab is hidden) and the queue refreshes every 15 seconds, so changes made by the matching engine, allocation updates or workers appear without a page reload. Nothing is kept in React-only or browser storage.

How stages map to the database (no new status is stored):

| Tracking stage | Source of truth |
|---|---|
| Pending | `emergency_requests.status` is `open` or `pending` and the request has no active work |
| Matching | status `open`/`pending` **and** an active, unexpired `reservation` lease or an allocation that is not yet confirmed (derived, never stored) |
| Partially Fulfilled | status `partially_fulfilled` — set by the DB when an allocation is `confirmed` and `quantity_fulfilled < quantity_requested` |
| Fulfilled | status `fulfilled` — set by the DB when confirmed allocations cover the request |
| Cancelled / Expired | terminal statuses |

Migration `0011` adds two database rules for this:

- `trg_requests_guard_status` rejects lifecycle transitions that the existing code never performs (allowed: `open ↔ pending`; `open`/`pending` → `partially_fulfilled`/`fulfilled`/`cancelled`/`expired`; `partially_fulfilled` → `fulfilled`/`cancelled`/`expired`; `fulfilled`, `cancelled` and `expired` are terminal).
- `trg_requests_log_status_change` writes a `request / status_changed` row into `allocation_history` for every status change, giving the timeline real database timestamps.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/requests/{id}/tracking` | Stage, database status, stepper, quantities, reservations, allocations, timeline. `404` if the request does not exist or is not visible to the caller's role, `403` for the owner role |

`GET /api/v1/requests` also returns `tracking_stage`, `quantity_remaining`, `quantity_reserved`, `quantity_in_progress` and `matching_active` per row.

#### Request → Match → Reserve → Allocate → Confirm (coordinator workflow)

From the tracking panel of a real request, a coordinator can run the whole workflow against the live database; every action re-reads the database state immediately and the queue row updates without a reload.

```text
Create request            POST /api/v1/requests                         emergency_requests 'open'   → Pending
Match request             POST /api/v1/match/requests/{id}/match        (existing MatchingEngine)
                            ST_DWithin candidates → score → FOR UPDATE SKIP LOCKED
                            reservation 'active' (1 h lease) + matching_decision + outbox
                            trigger: resources.quantity_available -= qty                     → Matching
Allocate lease            POST /api/v1/reservations/{id}/allocate
                            locks reservation + request rows; lease must be active & unexpired
                            reservation → 'completed' (quantity stays consumed)
                            allocation 'reserved' with reservation_id (UNIQUE)  — no double decrement
Dispatch                  POST /api/v1/allocations/{id}/transition {"status":"dispatched"}
(in transit / delivered)  … {"status":"in_transit"} / {"status":"delivered"}   (optional)
Confirm delivery          … {"status":"confirmed"}
                            existing trigger rolls quantity_fulfilled + request status up   → Partially Fulfilled / Fulfilled
Release lease             POST /api/v1/reservations/{id}/release          reservation 'cancelled', quantity returned
Cancel allocation         … {"status":"cancelled"} (only before delivery)  quantity returned
Preview candidates        GET  /api/v1/match/requests/{id}/candidates     read-only scoring, nothing reserved
```

Rules enforced:

- **Coordinator only:** allocate, release and transition return `403` for requester/owner tokens and `401` for an invalid token (`require_coordinator`). The database grants remain the enforcement point.
- **No double allocation:** row locks (`FOR UPDATE`) on the reservation and the request. `UNIQUE (allocations.reservation_id)` means a lease converts at most once even under concurrent calls. Resources stay protected by the existing `FOR UPDATE SKIP LOCKED` lease and the quantity triggers.
- **Matching never over-reserves:** the matching engine now locks the request row and subtracts quantity already committed (active leases plus unconfirmed allocations) from what it still has to cover.
- **Lifecycle rules:** the existing allocation state machine decides every transition (an invalid one returns `409` with the database message). The request guard from migration `0011` and `CHECK (quantity_fulfilled <= quantity_requested)` prevent over-fulfilment. Confirmed or delivered allocations cannot be cancelled through the API.
- **Audit everything:** database triggers write `allocation_history` rows for every reservation (new in migration `0012`), allocation and request change. Each API action also writes a transactional `event_outbox` event (`allocation_created`, `allocation_status_changed`, `allocation_confirmed`, `resource_returned`). `resource_returned` carries `zone_id`/`resource_type`, so the existing `EventProcessor` triggers incremental re-matching of the affected pools.

Tables involved: `emergency_requests`, `resources`, `reservation`, `allocations`, `matching_decision`, `allocation_history`, `event_outbox`, `pool`, `request_pool_dependency`, `owners`.

Authorization (see [Security](#security)): every endpoint except `/health` and the login endpoints requires a valid token (`401` otherwise — there is no anonymous or demo mode); a `requester` may only create and view its own requests (RLS); an `owner` gets `403` on request endpoints; matching, allocation, audit and re-match endpoints are coordinator-only (`403`).

### Matching Demo

Provides an interactive interface for executing:

- ResQLink incremental matching
- full-rescan baseline matching

and displaying available matching information returned by the backend.

### Spatial Map

Leaflet-based visualization of:

- resource locations
- request locations
- shelters
- zones
- hazard polygons

### Hazard Simulator — Resource Change → Incremental Re-matching

Applies a **real** change to a real resource and shows what the system actually did. Changes are mark unavailable, send to maintenance, return to service, set total stock, or move to another zone. Every resource change made anywhere (this page, the Resources page, the API) follows the same path:

```text
PATCH /api/v1/resources/{id}            one PostgreSQL transaction:
  ├─ lock resource row (FOR UPDATE) + its active leases (FOR UPDATE NOWAIT)
  ├─ revoke leases it can no longer honour     reservation → 'cancelled' (quantity returned, audited)
  ├─ update resource                            audit + ledger + location triggers (0013)
  └─ INSERT event_outbox 'resource_updated'     before/after state, affected zone(s), revoked leases
process the event (immediately after commit; the background EventProcessor uses the same code):
  ├─ claim the event row                        FOR UPDATE SKIP LOCKED, processed_at IS NULL
  ├─ affected pools                             pool rows for (old and new zone) × resource_type
  ├─ affected request IDs                       request_pool_dependency of those pools
  │                                             + requests whose lease was revoked
  ├─ MatchingEngine.incremental_rematch(pool)   existing engine, unchanged
  │   (+ match_request for revoked-lease requests outside those pools)
  └─ event_outbox.processed_at + processing_result (migration 0014)
```

Only requests depending on the affected pools, or which lost a lease, are re-matched. Requests for other resource types or other zones' pools are not touched.

The page shows:

- the resource state before and after the change;
- the leases revoked in the same transaction;
- the outbox event and when it was processed;
- the affected pools;
- each affected request: why it was affected, leased quantity before the change → after revocation → after re-matching, what is still uncovered, and the new leases;
- the number of requests re-matched, next to the number of open requests in the database;
- the measured re-match time;
- a list of recent runs read from `event_outbox.processing_result`.

The previous hard-coded figures (99.97 % saved, 10,000 requests, 1.45 ms) were removed; nothing on this page is estimated.

| Endpoint | Purpose |
|---|---|
| `PATCH /api/v1/resources/{id}` / `POST /api/v1/resources` | Change / create a resource; response includes `rematch` (the processed outcome) |
| `POST /api/v1/hazards/trigger-event` | Coordinator: write a `hazard_area_updated` event for an existing pool (`pool_id`) and re-match that pool's dependents (`404` for an unknown pool; no simulated values) |
| `GET /api/v1/hazards/rematch-runs` | Coordinator: recent processed events with their stored outcome |

Tables involved: `resources`, `reservation`, `event_outbox`, `pool`, `request_pool_dependency`, `emergency_requests`, `matching_decision`, `allocation_history`, `resource_ledger`, `resource_location_history`.

### Audit View

Displays operational history including:

- lifecycle changes
- reservation changes
- allocation changes
- timestamps
- event information

### Evaluation View

Visualizes the available Phase 7 evaluation outputs, ablations, and ground-truth comparisons.

---

## Disaster Scenario

The project includes a synthetic Chennai flood-response scenario covering:

- 5 operational zones
- shelters
- emergency resource owners
- emergency requesters
- emergency resources
- hazard polygons
- hazard events
- large-scale request datasets

The scenario includes both standard-scale and scale-testing datasets.

The ground-truth solver uses a PuLP/CBC Integer Linear Programming formulation for comparison against heuristic and database-driven matching approaches.

---

## Evaluation

The evaluation framework supports:

- baseline comparisons
- incremental matching evaluation
- ablation studies
- scalability analysis
- concurrency evaluation
- multi-seed experiments
- coverage analysis
- unmet demand analysis
- database work measurement
- latency measurement
- optimality comparison

Evaluation configurations include combinations of:

- distance
- urgency
- quantity
- temporal confidence
- pressure
- hazard accessibility
- incremental versus full-rescan execution

### Reported Evaluation Snapshot

The current project documentation reports the following evaluation figures:

| Metric | Reported Result |
|---|---:|
| Database work reduction | 99.97% |
| Incremental DB tuples evaluated | 312 |
| Full-scan baseline tuples | 100,000 |
| p95 match latency | 1.42 ms |
| Baseline p95 latency | ~4,850 ms |
| ILP optimality gap | 1.8% |
| Double allocations | 0 |

These figures should be treated as the project's current evaluation snapshot and should be revalidated against the final PostgreSQL/PostGIS deployment before being presented as live-system benchmark measurements.

---

## Security

Implemented in migration `0015` (`migrations/versions/0015_auth_and_db_security.py`, section 14 of `schema.sql`), `backend/app/security/`, `backend/app/api/deps.py`, `backend/app/api/endpoints_auth.py` and `backend/app/db/session.py`.

### Authentication

```text
POST /api/v1/auth/login  {username, password}
  → api_auth role → fn_auth_credentials()          (SECURITY DEFINER; api_auth cannot read any table)
  → PBKDF2-SHA256 verify (310k iterations, per-user salt; unknown users cost the same)
  → fn_auth_record_login()                          (5 failures → locked 15 min → 429)
  → signed JWT (HS256): sub = requester_id / owner_id / system_users.user_id, uid, role, name, iat, nbf, exp, iss, aud, jti
Every protected request:
  → signature, algorithm, exp, iss, aud, required claims       (401 if any fails)
  → fn_auth_session(uid, role, sub)                             (401 if the account was deactivated / role changed)
  → role check (require_coordinator / require_manager / …)     (403)
  → DB session: SET LOCAL ROLE api_<role> + jwt.claims.*        (GRANTs + RLS)
```

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/auth/login` | JSON login used by the web app. `200` token, `401` invalid credentials (same message for unknown users), `422` malformed body (a `role` field is rejected — the role comes from the account), `429` locked |
| `POST /api/v1/auth/token` | OAuth2 password form (Swagger “Authorize” button), same checks |
| `GET /api/v1/auth/me` | The authenticated identity |
| `GET /api/v1/requesters`, `GET /api/v1/requesters/{id}`, `GET|PATCH /api/v1/requesters/me` | Requester profiles: coordinator list is **masked** (`********0001`), coordinator detail and the requester's own profile are full, another requester's profile is `404` (RLS), owners `403`; a requester may change only its own contact phone/email |

The old `GET /auth/demo-token` (mint any role without credentials), the role-picking `/auth/token` and the "no token = coordinator" fallback were removed. Credentials live in `app_users` (RLS enabled, no policies, no grants to any API role); passwords are never stored in plain text (CHECK constraint on the hash format).

**Demo accounts** (seeded by `scripts/seed_data.sql`, demo only — they use the normal login path):

| Username | Role | Subject |
|---|---|---|
| `asha.verma` | coordinator | Asha Verma (system user) |
| `sdra.owner` | owner | State Disaster Response Agency |
| `coastal.owner` | owner | Coastal Relief NGO |
| `ramesh.kumar` | requester | Ramesh Kumar |
| `lakshmi.iyer` | requester | Lakshmi Iyer |

Shared demo password: `ResQLink-Demo-2026!`. Change or deactivate these accounts (`UPDATE app_users SET is_active = false …`) outside demos.

### Role permissions

| | requester | owner | coordinator |
|---|---|---|---|
| Requests | create / view **own** only (RLS); cannot change status or fulfilment | `403` (no grant) | all |
| Resources | read public columns of *available* resources (map); cannot modify | create / update **own** only (RLS `USING` + `WITH CHECK`); other owners' resources are invisible (`404`) | all |
| Match / allocate / dispatch / confirm / release | `403` | `403` | yes |
| Audit feed, re-match runs, hazard events | `403` | `403` | yes |
| Requester contact details | own only | none | masked in lists, full in detail view |

### Database-level enforcement (migration 0015)

- **Unprivileged login role.** The API logs in as `resqlink_app` — `NOSUPERUSER NOBYPASSRLS NOINHERIT`, no table privileges of its own. It can only act through `SET LOCAL ROLE` to `api_coordinator`, `api_owner`, `api_requester`, `api_service` (background re-matching, outbox, lease expiry, child-row reads after an RLS-checked parent read) or `api_auth` (login functions only).
- **Per-transaction role.** An `after_begin` hook (`app/db/session.py`) applies the role and `jwt.claims.*` at the start of **every** transaction, including the new transaction after a mid-request `commit()`. A session without a role refuses to run (fail closed). Previously a failed `SET ROLE` was silently ignored and statements after a commit ran as the superuser.
- **Least privilege (REVOKE then GRANT).** Coordinator: no `DELETE`/`TRUNCATE` anywhere, writes only to `resources`, `emergency_requests`, `reservation`, `allocations` (+ inserts into `pool`, `request_pool_dependency`, `event_outbox`, `matching_decision`). Requester: no `UPDATE` on `emergency_requests` (status / `quantity_fulfilled` were writable), no `INSERT/UPDATE` on `requesters` except column-level `UPDATE (contact_phone, contact_email)` (it could self-verify before), column-level `SELECT` on `resources` (no `owner_id`, notes). Owner: no `INSERT/UPDATE` on `owners` (any owner row was writable). `api_service`: column-level `SELECT` on `requesters`/`owners` without contact columns. `api_anon`: nothing. `PUBLIC` cannot `CREATE` in schema `public`.
- **RLS.** Existing policies on `resources`, `emergency_requests`, `requesters` now actually apply (the API no longer runs as the table owner); new RLS on `owners` (owner sees itself) and `app_users` (no policies); `api_service` policies for background work.
- **Append-only audit/ledger.** No API role can write `allocation_history`, `resource_ledger` or `resource_location_history`; they are written only by `SECURITY DEFINER` triggers (`fn_log_allocation_change` became one). Triggers block `UPDATE`/`DELETE`/`TRUNCATE` on all three, even for the table owner.
- **SECURITY DEFINER hygiene.** Every definer function pins `search_path` and has `EXECUTE` revoked from `PUBLIC`; `fn_assert_resource_manager` no longer trusts "no role".

### Frontend

Login page; the JWT is kept in `sessionStorage` (per tab); every call sends `Authorization: Bearer …`; a `401` (expired, tampered or revoked token) clears the session and returns to the login page; `401`/`403` never fall back to demo data; navigation and actions are role-aware (requester: Dashboard / Requests / Live Map / Evaluation; owner: Dashboard / Resources / Live Map / Evaluation; coordinator: everything). Hiding is a convenience — the API and PostgreSQL remain the enforcement layer.

### Not implemented yet (future improvements)

- Server-side token revocation / refresh tokens (logout is client-side; a deactivated account is rejected immediately via `fn_auth_session`, but a stolen token of an active account stays valid until `exp`, default 120 min).
- Self-service registration, password change/reset, MFA; per-IP rate limiting (lockout is per account).
- Key rotation / asymmetric (RS256) signing; HttpOnly-cookie session storage instead of `sessionStorage`.
- Row-level scoping of the coordinator role by agency or zone (coordinators currently see all rows).
- `SECRET_KEY`, `POSTGRES_PASSWORD` and `APP_DB_PASSWORD` in `docker-compose.yml` are development values — supply real secrets via environment variables in any shared deployment. The API logs a warning at startup for a default/short `SECRET_KEY` or a superuser / BYPASSRLS database login.

---

## Local Development

### Prerequisites

- Python 3.x
- Node.js and npm
- PostgreSQL with PostGIS for live database execution
- Docker Desktop for the containerized deployment

---

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

The development server is configured according to the frontend Vite configuration.

---

## Backend

From the project root:

```powershell
cd backend
pip install -r requirements.txt
$env:PYTHONPATH="."
uvicorn app.main:app --reload --port 8000
```

API documentation:

```text
http://localhost:8000/docs
```

---

## Database

`schema.sql` is the flattened equivalent of migrations `0001`–`0015` (including the login role / least-privilege grants / auth accounts of `0015`, the Phase 2b tables, the RLS roles/policies, the request-creation audit trigger, the request status guard/audit triggers and the reservation→allocation link/audit) and is what `docker-compose.yml` uses to initialise a fresh database volume.

> If you already have a Docker volume created from an older `schema.sql`, recreate it so the new schema is applied: `docker compose down -v` (this deletes local database data), then `docker compose up --build`.

Apply the Alembic migrations from the project environment (as the database owner / admin user):

```powershell
cd migrations
alembic upgrade head
```

Migration `0015` creates the API login role `resqlink_app` **without** a login or password (no secrets in migrations). Give it one before starting the API, and point `DATABASE_URL` at it:

```sql
ALTER ROLE resqlink_app LOGIN PASSWORD '<strong password>';
```

Docker does this automatically from `APP_DB_PASSWORD` (`scripts/docker/03_app_login_role.sh`).

Then load the required scenario/seed data using the project's database scripts.

---

## Docker Compose

The full architecture can be started using:

```powershell
docker compose up --build
```

To run in the background:

```powershell
docker compose up -d
```

To stop the stack:

```powershell
docker compose down
```

The Compose deployment is intended to run:

```text
React Frontend
      │
      ▼
FastAPI Backend
      │
      ▼
PostgreSQL + PostGIS
```

---

## Testing

### Backend Tests

```powershell
cd backend
python -m pytest -o asyncio_mode=auto tests
```

The live API tests run against the real database and are skipped automatically when it is unreachable. The API under test logs in as `resqlink_app` (`DATABASE_URL`); callers log in through `POST /api/v1/auth/login` with the seeded demo accounts; setup/verification SQL uses a separate admin connection (`ADMIN_DATABASE_URL`):

```powershell
cd backend
$env:DATABASE_URL="postgresql+asyncpg://resqlink_app:resqlink_app_password@localhost:5432/resqlink"
$env:ADMIN_DATABASE_URL="postgresql+asyncpg://resqlink:resqlinkpassword@localhost:5432/resqlink"
python -m pytest -o asyncio_mode=auto tests/test_auth_api.py tests/test_request_creation.py tests/test_request_tracking_api.py tests/test_allocation_flow_api.py tests/test_resource_management_api.py tests/test_resource_rematch_api.py -v
```

Request Status Tracking rule tests need no database:

```powershell
cd backend
python -m pytest tests/test_request_tracking_rules.py -v
```

### Frontend Production Build

```powershell
cd frontend
npm install
npm run build
```

The repository currently includes a backend test suite and frontend production build configuration.

Infrastructure-dependent tests should be executed against the actual PostgreSQL/PostGIS environment before final benchmark claims are made.

---

## Design Goals

ResQLink is designed around four primary goals:

### 1. Fast Adaptation

Reduce unnecessary re-computation when emergency resource availability changes.

### 2. Operational Correctness

Prevent concurrent requests from allocating the same resource.

### 3. Spatial Awareness

Use real geographic and hazard information instead of relying only on straight-line distance.

### 4. Measurable Database Efficiency

Evaluate the system using database work, latency, matching quality, scalability, concurrency, and comparison with optimization-based ground truth.

---

## Database Innovation Summary

The central contribution of ResQLink is not simply matching a request with the nearest resource.

The proposed architecture combines:

```text
Dependency Index
        +
Event-Driven Affected Set
        +
Incremental Re-Matching
        +
Temporal Confidence
        +
Hazard-Aware Accessibility
        +
Contention-Safe Leased Reservation
        +
PostgreSQL/PostGIS Transactions
```

This allows the database itself to participate directly in maintaining the operational state required for dynamic emergency resource coordination.

---

## SDG Relevance

ResQLink aligns with disaster-resilience and sustainable-development objectives, particularly:

- **SDG 11 — Sustainable Cities and Communities**
- **SDG 13 — Climate Action**

The system focuses on improving the coordination and utilization of emergency resources during climate-related disasters.

---

## Project Documentation

Additional technical documentation is available in:

- `CLAUDE.md`
- `DEVELOPMENT_PLAN.md`
- `PROJECT_OVERVIEW.md`
- `DBTHON_CHALLENGE.md`
- `NOVELTY_AND_PATENT_STRATEGY.md`
- `backend/docs/`
- `evaluation/README.md`
- `frontend/README.md`

---

## Intended Demonstration Flow

For a typical hackathon demonstration:

```text
1. Sign in (demo accounts in the Security section): as a requester,
   create a new emergency request from the Requests page;
   then sign in as the coordinator (asha.verma) and open the dashboard
2. Inspect the request from the Requests page
   and inspect the current emergency requests
   (the tracking panel opens and shows it as Pending)
3. View available resources on the map (add or update a resource
   on the Resources page — stock, availability, zone, mobility)
4. Select an urgent request
5. Run incremental matching
   (back on the Requests page the request now tracks as Matching)
6. Display the selected resource and reservation; allocate the lease,
   dispatch and confirm it — the request moves to Partially Fulfilled / Fulfilled
7. On the Hazard Simulator, take a leased resource out of service
   (or cut its stock / move it to another zone)
8. Show the affected pools and the affected request set, with each
   request's leases before the change, after revocation and after re-matching
9. Show that requests outside the affected pools were not re-matched
10. Compare against a full-rescan baseline (Matching Demo)
11. Inspect the audit trail
12. View evaluation results
```

This demonstrates the relationship between the database architecture, matching engine, operational workflow, and evaluation framework.

---

## License

This repository is intended for academic, research, and hackathon development purposes.

Refer to the repository for the applicable project license and usage terms.

---

## Authors

**ResQLink Team**

Developed for **DBTHON 2026**.
