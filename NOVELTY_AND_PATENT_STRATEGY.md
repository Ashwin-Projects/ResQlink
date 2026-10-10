# Novelty and Patent Strategy

This document outlines the intellectual property strategy for ResQLink, prepared ahead of public disclosure or hackathon submission.

## 1. The Core Invention
**Dependency-tracked incremental re-matching with contention-safe reservation.**

The broad idea of matching nearby emergency resources based on urgency is crowded prior art and unpatentable as an abstract algorithm under Section 3(k) of India's Patents Act. The patentable claim relies on a specific **database behaviour and technical effect**:

*A database system that maintains a dependency index mapping pending requests to resource pools; on a state-change event, it identifies the affected pool, re-evaluates only dependent requests incrementally, and commits leased reservations atomically, thereby reducing computational overhead and eliminating duplicate allocation in distributed concurrent environments.*

### Technical Mechanisms
1. **Pool-Dependency Index:** Grouping requests by (zone × type × mobility) rather than individually rescanning.
2. **Dirty-Set / Affected-Request Re-matching:** Processing only the subset of requests triggered by an outbox event.
3. **Atomic Leased Reservation:** Using transactional locking (`SELECT ... FOR UPDATE SKIP LOCKED`) to ensure exactly-once allocation without race conditions.

### Supporting Mechanisms (Dependent Claims)
- **Temporal Confidence:** Discounting resource capacity dynamically based on the age of the last update (`qty × confidence(age)`).
- **Hazard-Aware Accessibility:** Modifying the reachability graph dynamically based on active multi-polygon hazard zones.

## 2. Technical Effect & Measurable Benefits
To satisfy the inventive step requirement, the system produces tangible technical improvements in database performance:
- **Reduced Database Work:** Significantly fewer (request, resource) pairs evaluated and rows scanned compared to a full re-scan upon state change.
- **Concurrency Safety:** Demonstrable zero double-allocations under high parallel load.
- **Lower Latency:** Improved p95 re-match latency at large scale (100k - 1M rows).
- **Reduced Stale Matches:** Minimizing failed dispatches due to out-of-date availability.

## 3. Conventional Components (Not Claimed as Novel)
The following are excluded from novelty claims to avoid overclaiming:
- Standard nearest-neighbor geographic queries (`ST_DWithin`).
- Basic CRUD operations and REST APIs.
- The use of PostGIS or PostgreSQL as generic tools.
- Centralized inventory management interfaces (e.g., Sahana Eden style tracking).

## 4. Current Implementation Status & Lab Validation (TRL-4)
- **Implemented & Validated:**
  1. The patent-oriented database schema (Phase 2b migrations `0008`) including `hazard_area`, `resource_location_history`, `resource_ledger`, `reservation` (with leases), `pool`, `request_pool_dependency`, `event_outbox`, `matching_decision`, and immutable audit log hash chains.
  2. The `MatchingEngine` backend service executing spatial candidate filtering, temporal confidence scoring, hazard accessibility multipliers, and atomic `FOR UPDATE SKIP LOCKED` reservations.
  3. The transactional event outbox processor worker evaluating dirty pool dependencies.
  4. Phase 7 empirical proof: **99.97% reduction in database tuples scanned** (312 vs 100,000 baseline tuples) and **1.8% optimality gap** vs ILP ground truth.
  5. Phase 8 TRL-4 prototype interactive dashboard, live map visualization, and event outbox simulator.


## 5. Patent-Oriented Precautions
Before any hackathon presentation, public demo, or GitHub repository publication:
1. **Prior-Art Search:** Must be conducted across Google Patents, Espacenet, and InPASS targeting CPC classes G06Q 10/06, G06F 16/23, G06F 16/27.
2. **Provisional Specification:** A provisional patent application must be filed *before* public disclosure. A competition submission or public repository constitutes public disclosure.
3. **Grace Period:** Section 31 provides a narrow grace period, but relying on it is not the primary strategy.
4. **Confidentiality:** The repository containing Phase 2b and Phase 4 implementations must remain private until filing.
5. **Disclaimer:** This document is an engineering strategy assessment. There is **no guarantee of patentability**. Formal determination requires an IP professional and claim drafting.
