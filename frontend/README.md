# ResQLink Frontend — Phase 8 React + Vite Dashboard

The ResQLink frontend is a hackathon-demo-ready React + Vite application featuring Leaflet spatial maps, real-time matching engine triggers, event outbox hazard simulators, audit log viewers, and Phase 7 benchmark metrics.

## Features

1. **Main Dashboard:** High-level emergency response status, resource & request count cards, active leased locks, and DB work saved indicators.
2. **Resource View:** Live resource inventory (no fallback data) with **Add Resource** and **Edit** (stock, availability, zone/location, mobility, subtype, notes) plus audit history, stock ledger and location history per resource.
3. **Request View:** **Create Emergency Request** form, **Request Status Tracking** panel, and the live emergency request queue (tracking stage, remaining quantity, urgency badges, zone, "Track" and "Trigger Match" buttons). Users can create emergency requests directly through the ResQLink web application; see below.
4. **Matching Demo:** Interactive engine executor allowing mode comparison ("Incremental ResQLink" vs "Full Rescan Baseline") with distance, temporal confidence, and hazard accessibility score breakdowns.
5. **Live Map View:** Leaflet map with toggleable layers for emergency requests, available resources, shelters, and flood hazard area polygons.
6. **Hazard Simulator (Resource Change → Incremental Re-matching):** Applies a real change to a real resource (out of service, stock, zone). It shows the actual before/after state, revoked leases, the outbox event, the affected pools, the affected request IDs with their per-request outcome, real counts and the measured time, plus recent runs stored in `event_outbox.processing_result`. It contains no simulated or hard-coded figures.
7. **Audit Trail:** History log displaying state transitions, allocation changes, timestamps, and hash chain immutability indicators.
8. **Evaluation Suite:** Phase 7 benchmark visualizer displaying baseline vs ResQLink DB work, latency at scale, and ILP ground truth comparisons.

## Authentication

Files: `src/components/LoginView.jsx`, `src/auth/session.js`, `src/api/client.js`, `src/App.jsx`, `src/components/Navbar.jsx`.

- The app opens on a **login page** and makes no data calls until the user signs in through `POST /api/v1/auth/login`. The seeded demo accounts are listed on the page. Their password is in the root `README.md`, not in the UI.
- The returned JWT and user (`role`, `display_name`, `subject_id`) are kept in `sessionStorage`, one per browser tab. Every API call sends `Authorization: Bearer <token>`.
- A `401` (expired, tampered or revoked token, or a deactivated account) clears the session and returns to the login page with a notice. Sessions also expire client-side at the token's `exp`.
- `401` and `403` never fall back to demo data. `fetchWithFallback()` uses fallback data only when the network or server fails.
- **Role-aware UI.** Hiding a tab or button is a convenience; the API and PostgreSQL enforce the rules.
  - Navigation by role:
    - requester: Dashboard, Requests, Live Map, Evaluation;
    - owner: Dashboard, Resources, Live Map, Evaluation;
    - coordinator: all tabs.
  - "Trigger Match" only appears for coordinators.
  - Dashboard cards the role can't see show "—".
  - A map layer the role can't see stays empty.
- The navbar shows the signed-in user, their role and a **Sign out** button.

## Development & Building

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build production bundle
npm run build

# Preview build locally
npm run preview
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | FastAPI backend base URL (see `.env.example`). Vite reads it at **build/dev-server start**, so rebuild after changing it. |

## Create Emergency Request

Files: `src/components/CreateRequestForm.jsx`, `src/components/RequestView.jsx`, `src/api/client.js`.

- Reference data (requesters, zones, resource types, urgency levels, mobility classes) is loaded from `GET /api/v1/requests/form-options`; the allowed values come from the backend, which mirrors the database CHECK constraints.
- Client-side validation: required requester / resource type / quantity / urgency / zone, quantity `> 0` with at most 2 decimals, valid selections, latitude/longitude ranges (both or neither), needed-by in the future, description ≤ 1000 characters.
- UI states: loading options, idle, submitting (button + inputs disabled, spinner), success (shows the created request ID, resource type, quantity, urgency, zone and database-defined status), error (network, 401, 403, 409, 422 with per-field messages, 5xx).
- Submits `POST /api/v1/requests` with `source_channel: "web"` and an `idempotency_key`; a retry of the same draft reuses the key, so a network retry never creates a duplicate.
- On success the returned request is inserted at the top of the queue without a page reload.
- These calls use `requestJson()` in `src/api/client.js`, which never substitutes fallback/demo data. (Other pages still use the pre-existing `fetchWithFallback()` helper.)

Every call sends the signed-in user's JWT (see **Authentication** below); a requester sees only itself in the requester list and can only create requests for itself.

## Request Status Tracking

Files: `src/components/RequestTrackingPanel.jsx`, `src/components/RequestView.jsx`, `src/api/client.js` (`getRequestTracking`).

- Every queue row has a **Track** button; a request created from the form is tracked automatically.
- The panel shows the stage stepper (Pending → Matching → Partially Fulfilled → Fulfilled, or terminal Cancelled/Expired), the underlying database status, requested / fulfilled / remaining quantity with reserved and in-progress amounts, assigned resources (leased reservations and allocations with their timestamps), key timestamps and an audit-log timeline.
- Live updates without a page reload: the panel polls `GET /api/v1/requests/{id}/tracking` every 5 s (`TRACKING_POLL_MS`) while the tab is visible, and the queue refreshes every 15 s (`LIST_REFRESH_MS`). The tracked row in the queue is updated from each poll.
- Data comes only from the API (`requestJson()`, no fallback data). If a refresh fails, the panel keeps the last state it received from the API and says so.
- The queue's status filter and badges use the tracking stage; the raw database status is shown underneath when it differs (for example `Matching` / `db: open`).

## Add / Update Resource

Files: `src/components/ResourceView.jsx`, `src/components/ResourceForm.jsx`, `src/components/ResourceEditPanel.jsx`, `src/components/resourceLabels.js`, `src/api/client.js` (`listResourcesLive`, `getResourceFormOptions`, `getResourceDetail`, `createResource`, `updateResource`).

- **List and filters:** the list comes from `GET /api/v1/resources` and refreshes every 15 s. The type and status filters use the database values from `GET /api/v1/resources/form-options`.
- **Add Resource:** shown only when `can_manage` is true (coordinator or owner). It has client-side validation: required fields, quantity ≥ 0 with at most 2 decimals, available ≤ total, coordinates in range and both or neither, and length limits. It posts to `POST /api/v1/resources`. On success the list re-reads the database and the new row is highlighted.
- **Edit panel:** loads `GET /api/v1/resources/{id}` and sends only the changed fields to `PATCH /api/v1/resources/{id}`. Total stock can't go below the quantity in use, and `depleted` is shown but not selectable. After a save, or after a refused save, it re-reads values, audit history, stock ledger and location history from the database, so what it shows always matches PostgreSQL.
- **Read-only users:** they see the same data with a **Details** button instead of Edit.

The Live Map and Dashboard still read `/api/v1/map/resources` through the older `fetchWithFallback()` helper.

Every resource save returns the incremental re-match outcome (`rematch`); the Edit panel's success message reports how many dependent requests were re-evaluated and how many leases were created or revoked. The stock field's hint explains that cutting below the in-use quantity revokes active leases, while allocated or consumed quantity is a hard minimum.

## Hazard Simulator — Resource Change → Incremental Re-matching

File: `src/components/HazardDemoView.jsx`. API calls: `listResourcesLive`, `getResourceFormOptions`, `updateResource` and `getRematchRuns`; `triggerHazardEvent` is now a strict call too.

1. Pick a resource from the live list and a change: mark unavailable, maintenance, return to service, set total stock, or move to another zone.
2. **Apply** sends `PATCH /api/v1/resources/{id}`. The panel then shows the response:
   - before/after resource state and the leases revoked in the same transaction;
   - the outbox event status and processing time;
   - the affected pools;
   - a table of affected requests: reason (pool dependency / lease revoked), leased quantity before the change → after revocation → after re-match, what is still to cover, and the new leases;
   - the number of requests re-matched and the number of open requests in the database;
   - the measured re-match time.
3. **Recent re-match runs** lists `GET /api/v1/hazards/rematch-runs` (stored results); it refreshes after every change.

All calls use `requestJson()`: no fallback data, and errors (for example a `409` when the stock would drop below allocated quantity) are shown as returned.

## Match → Reserve → Allocate → Confirm (coordinator actions)

The tracking panel (`RequestTrackingPanel.jsx`) is also where a coordinator runs the real workflow. The panel shows these controls only when the API reports `can_manage: true` (coordinator role); other roles see a read-only panel.

| Control | API call |
|---|---|
| **Match request** (disabled when nothing is left to cover) | `POST /api/v1/match/requests/{id}/match` |
| **Show candidates** — ranked candidates with available quantity, distance and score components; nothing reserved | `GET /api/v1/match/requests/{id}/candidates` |
| **Allocate** on an active lease | `POST /api/v1/reservations/{id}/allocate` |
| **Release** on an active lease | `POST /api/v1/reservations/{id}/release` |
| **Dispatch / In transit / Mark delivered / Confirm delivery / Cancel** on an allocation (offered per current status, `ALLOCATION_ACTIONS`) | `POST /api/v1/allocations/{id}/transition` |

After every action the panel re-reads `GET /api/v1/requests/{id}/tracking` before it shows the result message, so the message, quantities, stage and lists always reflect the database. Errors from the database (an invalid transition, an expired lease, an already converted lease, or a role that isn't allowed) are shown as returned by the API. Reservation rows show the matching score and its components from `matching_decision`. Allocation rows show the matched, dispatched and confirmed times and the distance.

All workflow calls use `requestJson()` (no fallback data). The separate **Matching Demo** page still uses the older `fetchWithFallback()` helper.
