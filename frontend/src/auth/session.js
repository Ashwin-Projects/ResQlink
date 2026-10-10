// Client-side session for the signed JWT returned by POST /api/v1/auth/login.
//
// Kept in sessionStorage (per browser tab, cleared when the tab closes) rather
// than localStorage, with an in-memory fallback when storage is unavailable.
// The token is only a bearer credential: every protected endpoint re-validates
// it (signature, expiry, active account) and PostgreSQL enforces the role's
// GRANTs / RLS. The role kept here only decides which actions the UI shows.

const KEY = 'resqlink.session';
const listeners = new Set();
let memory = null;
let lastLogoutReason = null;

function decodePayload(token) {
  try {
    const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(part + '='.repeat((4 - (part.length % 4)) % 4)));
  } catch {
    return null;
  }
}

function read() {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* storage unavailable */ }
  return memory;
}

function notify(session) {
  listeners.forEach((fn) => {
    try { fn(session); } catch { /* a listener error must not break auth */ }
  });
}

export function getSession() {
  const s = read();
  if (!s || !s.token) return null;
  if (s.expiresAt && Date.now() >= s.expiresAt) {
    clearSession('Your session has expired. Please sign in again.');
    return null;
  }
  return s;
}

export function getToken() {
  return getSession()?.token || null;
}

export function setSession(loginResponse) {
  const claims = decodePayload(loginResponse.access_token) || {};
  const session = {
    token: loginResponse.access_token,
    expiresAt: claims.exp ? claims.exp * 1000 : Date.now() + (loginResponse.expires_in || 0) * 1000,
    user: loginResponse.user,          // { user_id, subject_id, role, display_name }
  };
  memory = session;
  try { window.sessionStorage.setItem(KEY, JSON.stringify(session)); } catch { /* memory only */ }
  notify(session);
  return session;
}

export function clearSession(reason = null) {
  const had = !!read();
  memory = null;
  try { window.sessionStorage.removeItem(KEY); } catch { /* ignore */ }
  if (reason) lastLogoutReason = reason;
  if (had) notify(null);
}

export function consumeLogoutReason() {
  const r = lastLogoutReason;
  lastLogoutReason = null;
  return r;
}

export function onSessionChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// UI-only capability map (mirrors the backend rules; the API and the database
// remain the enforcement layer — hiding a tab is a convenience, not security).
export const ROLE_CAPABILITIES = {
  coordinator: { tabs: ['dashboard', 'resources', 'requests', 'matching', 'map', 'hazard_sim', 'audit', 'evaluation'], canMatch: true },
  owner: { tabs: ['dashboard', 'resources', 'map', 'evaluation'], canMatch: false },
  requester: { tabs: ['dashboard', 'requests', 'map', 'evaluation'], canMatch: false },
};

export function capabilitiesFor(role) {
  return ROLE_CAPABILITIES[role] || { tabs: [], canMatch: false };
}
