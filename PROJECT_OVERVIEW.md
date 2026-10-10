# ResQLink Project Overview

## 1. Problem & Domain
During flood and cyclone disaster responses, visibility of critical emergency resources (boats, generators, medical supplies, shelters) is highly fragmented across government agencies, NGOs, and private citizens.
**Existing limitations:** Current centralized inventory systems (like Sahana Eden) support matching but fall short when availability changes rapidly. A status change usually triggers a manual re-search or a full, computationally expensive re-scan of all pending requests. This leads to wasted database work, failed dispatches due to stale availability, and double-allocation of scarce resources under concurrency. Furthermore, straight-line distance metrics ignore hazard areas like flooded roads.

## 2. Proposed Solution
**ResQLink** is an event-driven emergency resource coordination system. It moves away from naive "nearest-first" dispatch by treating resource allocation as an incremental, state-aware concurrency problem. 

## 3. Core Innovation
The technical heart of ResQLink is **Dependency-tracked incremental re-matching with contention-safe reservation**.
- **Pool-Dependency Index:** Pending requests are mapped to resource pools (zone × type × mobility).
- **Incremental Re-matching:** When a resource state changes, an event is emitted. The system identifies the affected pool and re-evaluates *only* the requests dependent on that pool, avoiding full dataset rescans.
- **Atomic Reservation:** Allocation utilizes row-level database locking (`FOR UPDATE SKIP LOCKED`) and temporary leases to eliminate double-allocation race conditions completely.

## 4. Supporting Mechanisms
- **Temporal Confidence:** Effective resource capacity decays based on the age of the last update (`qty × confidence(age)`).
- **Hazard-Aware Accessibility:** Match scoring evaluates mobility-specific reachability (e.g., boat vs. truck) using PostGIS hazard polygons, penalizing or blocking routes through active flood zones.

## 5. Architecture & Components
- **Database (PostgreSQL/PostGIS):** The source of truth for spatial data, row-locking, schema-enforced state transitions, and the `LISTEN/NOTIFY` outbox pattern.
- **Backend API:** Orchestrates CRUD, authentication, and runs the worker processes that consume events and execute the matching algorithm.
- **Frontend Dashboard:** A real-time (WebSocket/SSE) map-based interface showing hazard polygons, live resource status, and ranked request queues.

## 6. Evaluation & Validation
The system's technical effect will be measured via a synthetic scale generator (up to 1M rows) and an ILP (Integer Linear Programming) optimal baseline.
**Metrics:**
- Percentage of database rows/pairs evaluated (incremental vs. full re-scan).
- Zero double-allocations under high concurrency.
- p95 re-match latency under load.

## 7. SDGs and Impact
- **SDG 11.5:** Reduce deaths and direct economic losses caused by disasters.
- **SDG 13.1:** Strengthen resilience and adaptive capacity to climate-related hazards.
- **SDG 3:** Good health and well-being (rapid medical supply dispatch).
- **SDG 17:** Partnerships for the goals (unifying NGO, government, and private resources).

## 8. Technology Readiness Level (TRL)
- **Current Target:** **TRL 4** (Lab-validated prototype using simulated disaster geography and synthetic request streams).
- **Future Target:** TRL 5-6 (Pilot deployment in a district control room).

## 9. Scope and Limitations (Actual Implementation Status)
*Disclaimer: As of the current repository state, ResQLink consists of the Phase 1 conceptual models and the Phase 2 baseline database schema/migrations. The core innovation features (incremental re-matching, temporal confidence, hazard routing), backend APIs, frontend interfaces, and evaluation harnesses are fully designed but **not yet implemented**.*
