# ResQLink Matching Logic

## Core Innovation
The foundational technical mechanism for ResQLink is **Dependency-tracked incremental re-matching with contention-safe reservation.**
This document outlines the Phase 4 algorithmic implementation governing how emergency requests evaluate resource candidates.

## 1. Candidate Retrieval (PostGIS Filtering)
When evaluating a request, we first apply raw geographic boundaries instead of scoring every resource in the database.
- Uses `ST_DWithin` filtering candidates exactly bounded by `max_distance_meters` (50km defaults).
- Utilizes existing GiST indexes for O(log n) geometry bounding box evaluations.

## 2. Contention-Safe Reservation
Once candidates are ranked, they must be leased safely:
- The engine uses `SELECT ... FOR UPDATE SKIP LOCKED` inside a transaction.
- Concurrent workers will skip locked resources and gracefully move to the next candidate instead of failing completely.
- A `reservation` row is atomically written with an explicit `lease_expires_at` representing temporary ownership until physical dispatch confirms it.

## 3. Scoring Components
The `score` of a candidate is reproducible based on the following metrics:
- **Spatial Distance Penalty**: Linear penalty normalized against the bounding radius `(1.0 - (distance / max))`.
- **Temporal Confidence**: Time-decay confidence score. A `last_verified_at` timestamp currently set starts at `1.0` confidence and logarithmically decays to `0.1` after 72 hours, recognizing that unverified assets during disasters become unreliable quickly.
- **Hazard Accessibility**: A mobility multiplier. Assumes air assets (`1.0`) bypass hazard boundaries easily, boats (`0.9`), while standard ground mobility takes penalties crossing intersections.
- **Urgency Bonus**: Hardcoded standard bonuses scaling based on `critical` vs `medium`.

**Score Formula**:
`((1.0 - distance_norm) * confidence * hazard_accessibility) + urgency_bonus`

## 4. Incremental Re-Matching vs. Full-Rescan
To prevent massive DB load surges during constant telemetry updates:
- **Full-Rescan Baseline**: Identifies and loops all `open`/`pending` requests natively. Available via `/engine/full-rescan`.
- **Incremental Core Invention**: Available via `/engine/incremental/{pool_id}`. Uses the `request_pool_dependency` relationship to precisely load only the affected fraction of pending requests that physically interact with the state change. 

## 5. Decision Explainability
Every match natively outputs a JSON `MatchingDecision` record inserted into the database logging the exact internal score components computed at that very millisecond.
