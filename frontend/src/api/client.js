import { getToken, clearSession } from '../auth/session';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

// Every call carries the signed JWT from the login session. A 401 means the
// token is missing / expired / revoked: the session is cleared and the app
// returns to the login screen. No call substitutes demo / fallback data: if the
// API fails, the page shows an error state.
function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function handleUnauthorized(status) {
  if (status === 401) clearSession('Your session has expired or is no longer valid. Please sign in again.');
}

// ---------------------------------------------------------------------------
// API calls (no fallback data): what the UI shows is always what
// FastAPI / PostgreSQL returned.
// ---------------------------------------------------------------------------
export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'unknown', fieldErrors = {} } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;      // HTTP status (0 = no response)
    this.kind = kind;          // network | auth | forbidden | validation | conflict | server | unknown
    this.fieldErrors = fieldErrors; // { field_name: message } from FastAPI 422 details
  }
}

function parseErrorDetail(detail) {
  // FastAPI returns either a string or a list of {loc, msg, type}.
  if (typeof detail === 'string') return { message: detail, fieldErrors: {} };
  if (Array.isArray(detail)) {
    const fieldErrors = {};
    const messages = [];
    for (const item of detail) {
      const loc = Array.isArray(item.loc) ? item.loc.filter(p => p !== 'body') : [];
      const field = loc.length ? String(loc[loc.length - 1]) : null;
      const msg = (item.msg || 'Invalid value').replace(/^Value error, /, '');
      if (field && !fieldErrors[field]) fieldErrors[field] = msg;
      messages.push(field ? `${field}: ${msg}` : msg);
    }
    return { message: messages.join('; ') || 'Validation failed', fieldErrors };
  }
  return { message: 'Request failed', fieldErrors: {} };
}

async function requestJson(url, options = {}) {
  let res;
  try {
    res = await fetch(`${BASE_URL}${url}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.anonymous ? {} : authHeaders()), ...(options.headers || {}) },
    });
  } catch (err) {
    throw new ApiError(`Cannot reach the ResQLink API at ${BASE_URL}. Check that the backend is running.`, { kind: 'network' });
  }

  let body = null;
  const text = await res.text();
  if (text) {
    try { body = JSON.parse(text); } catch { body = null; }
  }

  if (res.ok) return { status: res.status, data: body };
  if (!options.anonymous) handleUnauthorized(res.status);

  const { message, fieldErrors } = parseErrorDetail(body?.detail);
  const kind =
    res.status === 401 ? 'auth' :
    res.status === 403 ? 'forbidden' :
    res.status === 409 ? 'conflict' :
    res.status === 429 ? 'locked' :
    (res.status === 422 || res.status === 400) ? 'validation' :
    res.status >= 500 ? 'server' : 'unknown';
  throw new ApiError(message || `HTTP ${res.status}`, { status: res.status, kind, fieldErrors });
}

export const api = {
  // Auth: username + password -> signed JWT (no token is ever issued without a password check)
  // expectedRole: the role chosen on the sign-in screen. The server refuses a
  // mismatch (403); the token's role always comes from the account.
  login: async (username, password, expectedRole) => {
    const { data } = await requestJson('/api/v1/auth/login', {
      method: 'POST', anonymous: true,
      body: JSON.stringify({ username, password, ...(expectedRole ? { expected_role: expectedRole } : {}) }),
    });
    return data;   // { access_token, token_type, expires_in, user: { user_id, subject_id, role, display_name } }
  },
  // Public sign-up (requester: active; owner: pending coordinator verification).
  register: async (payload) => {
    const { data } = await requestJson('/api/v1/auth/register', {
      method: 'POST', anonymous: true, body: JSON.stringify(payload),
    });
    return data;   // { user_id, username, role, status: 'active' | 'pending_approval', message }
  },
  me: async () => {
    const { data } = await requestJson('/api/v1/auth/me');
    return data;
  },

  // Dashboard counts, computed under the caller's database role (RLS)
  getDashboardStats: async () => (await requestJson('/api/v1/dashboard/stats')).data,

  // Live Map layers (GET /api/v1/map/*)
  getResources: async () => (await requestJson('/api/v1/map/resources')).data,
  getRequests: async () => (await requestJson('/api/v1/map/requests')).data,
  getShelters: async () => (await requestJson('/api/v1/map/shelters')).data,
  getZones: async () => (await requestJson('/api/v1/map/zones')).data,
  getHazards: async () => (await requestJson('/api/v1/map/hazards')).data,

  // Emergency requests — live database only (no fallback data)
  listEmergencyRequests: async ({ limit = 200 } = {}) => {
    const { data } = await requestJson(`/api/v1/requests?limit=${limit}`);
    return data;
  },

  getRequestFormOptions: async () => {
    const { data } = await requestJson('/api/v1/requests/form-options');
    return data;
  },

  // Request Status Tracking — live database state for one request
  getRequestTracking: async (requestId) => {
    const { data } = await requestJson(`/api/v1/requests/${encodeURIComponent(requestId)}/tracking`);
    return data;
  },

  // Resource management (live API only)
  listResourcesLive: async ({ limit = 500 } = {}) => {
    const { data } = await requestJson(`/api/v1/resources?limit=${limit}`);
    return data;
  },
  getResourceFormOptions: async () => {
    const { data } = await requestJson('/api/v1/resources/form-options');
    return data;
  },
  getResourceDetail: async (resourceId) => {
    const { data } = await requestJson(`/api/v1/resources/${encodeURIComponent(resourceId)}`);
    return data;
  },
  createResource: async (payload) => {
    const { data } = await requestJson('/api/v1/resources', { method: 'POST', body: JSON.stringify(payload) });
    return data;
  },
  updateResource: async (resourceId, changes) => {
    const { data } = await requestJson(`/api/v1/resources/${encodeURIComponent(resourceId)}`, {
      method: 'PATCH', body: JSON.stringify(changes),
    });
    return data;
  },

  // Request -> Match -> Reserve -> Allocate -> Confirm workflow (live API only)
  matchRequest: async (requestId, mode = 'incremental') => {
    const { data } = await requestJson(`/api/v1/match/requests/${encodeURIComponent(requestId)}/match?mode=${mode}`, { method: 'POST' });
    return data;
  },
  getMatchCandidates: async (requestId) => {
    const { data } = await requestJson(`/api/v1/match/requests/${encodeURIComponent(requestId)}/candidates`);
    return data;
  },
  allocateReservation: async (reservationId) => {
    const { data } = await requestJson(`/api/v1/reservations/${encodeURIComponent(reservationId)}/allocate`, { method: 'POST', body: JSON.stringify({}) });
    return data;
  },
  releaseReservation: async (reservationId) => {
    const { data } = await requestJson(`/api/v1/reservations/${encodeURIComponent(reservationId)}/release`, { method: 'POST' });
    return data;
  },
  transitionAllocation: async (allocationId, status) => {
    const { data } = await requestJson(`/api/v1/allocations/${encodeURIComponent(allocationId)}/transition`, {
      method: 'POST', body: JSON.stringify({ status }),
    });
    return data;
  },

  // POST /api/v1/requests -> { status: 201 | 200 (idempotent replay), data: created request }
  createEmergencyRequest: async (payload) => {
    return requestJson('/api/v1/requests', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  // Pool-level event -> real outbox event + incremental re-match (no fallback data)
  triggerHazardEvent: async (eventPayload) => {
    const { data } = await requestJson('/api/v1/hazards/trigger-event', {
      method: 'POST', body: JSON.stringify(eventPayload),
    });
    return data;
  },

  // Stored outcomes of processed re-match events (event_outbox.processing_result)
  getRematchRuns: async (limit = 10) => {
    const { data } = await requestJson(`/api/v1/hazards/rematch-runs?limit=${limit}`);
    return data;
  },

  // Audit activity feed (allocation_history, newest first)
  getActivityFeed: async (limit = 50) => (await requestJson(`/api/v1/audit/activity-feed?limit=${limit}`)).data,

  // Evaluation results read from evaluation/results/*.json by the API
  getEvaluationResults: async () => (await requestJson('/api/v1/evaluation/results')).data,
};
