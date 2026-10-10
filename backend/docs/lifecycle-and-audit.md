# ResQLink Lifecycle and Audit

## Allocation State Machine
The core lifecycle traces a rigorous path natively constrained by database checks and triggers (Phase 2b).

**Allowed Standard Path:**
`pending` → `matched` → `proposed` → `reserved` → `dispatched` → `confirmed` → `fulfilled`

**Allowed Branches:**
- `rejected`, `expired`, `cancelled`, `reassigned`.

Database integrity triggers prevent illegal transitions like `fulfilled` moving backward to `pending`.

## Immutable Audit Trail
NFR6 enforcement demands a strictly append-only audit architecture.
- Any allocation state transitions are intercepted by database triggers natively recording the `old_value` and `new_value` inside `allocation_history`.
- The database trigger `fn_prevent_history_mutation` forcefully raises exceptions preventing any `UPDATE` or `DELETE` regardless of application roles.

## Ranked Request Queue
Requests competing for scarce resources do not strictly evaluate FIFO.
The `RequestQueueService` computes a continuous composite score preventing starvation:
- `Score = (UrgencyWeight) + (WaitHours * Factor)`
- A `low` priority request will eventually overtake a brand new `critical` request if left abandoned for several days.

## Lease Expiration and Re-queueing
- The `LeaseExpirer` acts as a background queue processor operating against `reservation.lease_expires_at`.
- Utilizes `FOR UPDATE SKIP LOCKED` isolating parallel expiry sweeps.
- When an expiry strikes, it atomically pushes a `reservation_expired` payload to the `event_outbox`.
- The `EventProcessor` reads the outbox, notes the pool the resource belongs to, and safely triggers the matching engine incrementally against only dependent requests.

## Dispatched Allocation Failure / Reassignment
The `LifecycleService` addresses allocations that entered `dispatched` state but were abandoned before `confirmed`. They are transitioned to `reassigned`, issuing a `resource_returned` event which loops back into the incremental rematching queue identically to an expiry.
