# ResQLink - AI Agent Instructions

## 1. Project Purpose
ResQLink is a database-driven emergency resource coordination system designed for flood/cyclone disaster response. It centralizes visibility of emergency resources (generators, boats, medical supplies, volunteers) and matches them to emergency requests in real-time. The primary technical goal is to solve the problem of inefficient, full re-computation during rapidly changing resource availability by using **dependency-tracked incremental re-matching** with **contention-safe atomic reservations**.

## 2. Actual Current State
- **Phase 1 (Data Modeling):** Completed ✅
- **Phase 2 (Base Schema & Migrations):** Completed ✅
- **Phase 2b (Schema Upgrades for Core Invention):** Completed ✅ (`hazard_area`, `resource_ledger`, `reservation`, `pool`, `request_pool_dependency`, `event_outbox`).
- **Phase 3 (Core API & Security):** Completed ✅ (FastAPI, RLS security, JWT auth).
- **Phase 4 (Matching Engine):** Completed ✅ (`ST_DWithin` spatial retrieval, temporal confidence, hazard accessibility multiplier, `FOR UPDATE SKIP LOCKED` reservations).
- **Phase 5 (Disaster Scenario):** Completed ✅ (5 zones, 10k requests dataset, ILP ground truth key).
- **Phase 6 (Lifecycle & Audit):** Completed ✅ (Lease expiry, immutable audit log hash chains).
- **Phase 7 (Evaluation):** Completed ✅ (Ablation suite, latency & DB work saved metrics).
- **Phase 8 (Dashboard & Integration):** Completed ✅ (React + Vite Leaflet dashboard, event outbox simulator, Docker deployment setup).
- **Feature Iteration — Authentication + DB-Level Security:** Completed ✅ (real login `POST /api/v1/auth/login` → PBKDF2 + PyJWT; every router authenticated, coordinator-only matching/allocation/audit/hazards; API logs in as unprivileged `resqlink_app` and an `after_begin` hook applies `SET LOCAL ROLE api_<role>` + claims to EVERY transaction (fail closed); `api_service` for background work, `api_auth` for login functions; least-privilege GRANT/REVOKE, RLS on `owners`/`app_users`, append-only ledgers; masked requester contact data; login page + role-aware UI; migration `0015`).
- **Feature Iteration — Create Emergency Request:** Completed ✅ (React form → `POST /api/v1/requests` → single PostgreSQL transaction: request + pool dependency + outbox event + trigger-written audit row). Migration `0010`.
- **Feature Iteration — Resource Change → Incremental Re-matching:** Completed ✅ (resource change revokes leases it can no longer honour in the same transaction; `resource_updated` outbox event → affected pools → `request_pool_dependency` → existing `MatchingEngine.incremental_rematch` for dependents only; outcome stored in `event_outbox.processing_result`; `services/rematch.py`, migration `0014`; Hazard Simulator shows real results only).
- **Feature Iteration — Add / Update Resource:** Completed ✅ (`POST/PATCH/GET /api/v1/resources[/{id}]`, `/resources/form-options`; coordinator or owner (RLS); stock changes protect in-use quantity; DB trigger writes audit + `resource_ledger` + `resource_location_history`, migration `0013`).
- **Feature Iteration — Request → Match → Reserve → Allocate → Confirm:** Completed ✅ (coordinator APIs `/reservations/{id}/allocate|release`, `/allocations/{id}/transition`, `/match/requests/{id}/candidates`; reservation→allocation exactly-once via `allocations.reservation_id` UNIQUE + row locks; reservation audit; migration `0012`).
- **Feature Iteration — Request Status Tracking:** Completed ✅ (`GET /api/v1/requests/{id}/tracking`; Pending → Matching (derived from active leases / unconfirmed allocations) → Partially Fulfilled → Fulfilled; request status guard + status-change audit triggers, migration `0011`; live-polling tracking panel).

## 3. Finalized Architecture
- **Database (The Core):** PostgreSQL 14+ with PostGIS. Handles spatial indexing (GiST), temporal state, row-level locking (`FOR UPDATE SKIP LOCKED`), and event outbox pattern.
- **Backend:** Python / FastAPI REST API (`backend/app/main.py`), SQLAlchemy async session, RLS role enforcement.
- **Frontend:** React + Vite (`frontend/`), Leaflet live maps, event simulator, evaluation visualizer.
- **Deployment:** Docker Compose setup (`docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`).

## 4. Core Invention
The system's novelty lies in its database-level behavior:
**Dependency-tracked incremental re-matching with contention-safe reservation.**
Instead of a full rescan when a resource's status changes, the database maintains a `pool-dependency index`. An event outbox triggers a worker to re-evaluate *only* the pending requests dependent on the affected pool. Allocations use atomic, leased reservations.

## 5. Technology Stack
- **RDBMS:** PostgreSQL + PostGIS extension.
- **Migrations:** Alembic (raw SQL migrations `0001` - `0015`). `schema.sql` must stay the flattened equivalent of all migrations (Docker initialises from it).
- **Backend/API:** Python 3.11+, FastAPI, SQLAlchemy Core/Async, GeoAlchemy2, Pydantic.
- **Frontend:** React, Vite, Leaflet, Lucide React.


## 6. Database / Concurrency / Security Rules
- **Concurrency is a Correctness Property:** Always use row-level locking (`FOR UPDATE SKIP LOCKED`) for matching/reservations.
- **Outbox Pattern:** State changes and event emissions must happen in the *same* database transaction using an `event_outbox` table. `LISTEN/NOTIFY` only wakes the worker; it is not the durable source of truth.
- **Row-Level Security (RLS):** Implement RLS for multi-tenant data protection (owners, requesters, coordinators).
- **Append-Only Ledgers:** Resource quantities are managed via an insert-only `resource_ledger`. Audit logs (`audit_log`) must be immutable (no UPDATE/DELETE), optionally secured with a hash chain.

## 7. Coding Rules
- Do NOT invent implementation that does not exist. Acknowledge missing features.
- Write raw SQL for migrations, especially for PostGIS geometry, triggers, and complex constraints. Do not rely heavily on ORM autogeneration for DDL.
- Follow a strict phase-by-phase progression. Do not start a new phase until the previous one is fully complete, tested, and verified.

## 8. Phase Progression Rules
- **Next Phase:** **Phase 2b (Alembic Migrations for Novelty Features)**.
- Do not implement Phase 3 or 4 until Phase 2b is merged and tested.
- Maintain the exact schema terminology outlined in the Final Plan.

**INSTRUCTION:** Read this `CLAUDE.md` file completely before beginning any new work or conversation to ensure alignment with the current state and patent-oriented architecture.
