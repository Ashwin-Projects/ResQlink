import React, { useState } from 'react';
import { LogIn, Loader2, AlertTriangle, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { setSession } from '../auth/session';

// Seeded demo accounts (scripts/seed_data.sql). They sign in through the same
// POST /api/v1/auth/login path as any account; the demo password is documented
// in README.md, not shipped in the UI.
const DEMO_ACCOUNTS = [
  { username: 'asha.verma', role: 'coordinator', who: 'Asha Verma — matching, allocation, audit' },
  { username: 'sdra.owner', role: 'owner', who: 'State Disaster Response Agency — own resources' },
  { username: 'coastal.owner', role: 'owner', who: 'Coastal Relief NGO — own resources' },
  { username: 'ramesh.kumar', role: 'requester', who: 'Ramesh Kumar — own requests' },
  { username: 'lakshmi.iyer', role: 'requester', who: 'Lakshmi Iyer — own requests' },
];

function loginErrorMessage(err) {
  switch (err?.kind) {
    case 'auth': return 'Invalid username or password.';
    case 'locked': return 'Too many failed attempts. This account is temporarily locked — try again later.';
    case 'validation': return 'Enter a username (3–64 characters) and a password.';
    case 'network': return err.message;
    default: return err?.message || 'Sign-in failed.';
  }
}

export default function LoginView({ notice }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [state, setState] = useState('idle'); // idle | submitting
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('Enter your username and password.');
      return;
    }
    setState('submitting');
    setError(null);
    try {
      const res = await api.login(username.trim(), password);
      setPassword('');
      setSession(res);            // App re-renders into the authenticated shell
    } catch (err) {
      setError(loginErrorMessage(err));
      setState('idle');
    }
  };

  return (
    <div className="login-shell">
      <div className="card login-card">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">RQ</div>
          <div>
            <div className="brand-title">ResQLink</div>
            <div className="brand-subtitle">Emergency Resource Coordination</div>
          </div>
        </div>

        <h1 className="login-heading">Sign in to the operations console</h1>
        <p className="login-lead">
          Your role — coordinator, resource owner or requester — comes from your account and is enforced by the API and by PostgreSQL row-level security.
        </p>

        {notice && !error && (
          <div className="alert alert-info" role="status" data-testid="login-notice"><ShieldCheck size={16} /><div>{notice}</div></div>
        )}
        {error && (
          <div className="alert alert-error" role="alert" data-testid="login-error"><AlertTriangle size={16} /><div>{error}</div></div>
        )}

        <form onSubmit={submit} noValidate aria-label="Sign in">
          <div className="form-group">
            <label className="form-label" htmlFor="login-username">Username</label>
            <input id="login-username" className="form-input" autoComplete="username" autoFocus
                   value={username} onChange={(e) => setUsername(e.target.value)} maxLength={64} />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="login-password">Password</label>
            <input id="login-password" className="form-input" type="password" autoComplete="current-password"
                   value={password} onChange={(e) => setPassword(e.target.value)} maxLength={256} />
          </div>
          <button type="submit" className="btn btn-lg btn-block" disabled={state === 'submitting'}>
            {state === 'submitting' ? <Loader2 size={16} className="spin" /> : <LogIn size={16} />}
            <span>{state === 'submitting' ? 'Signing in…' : 'Sign in'}</span>
          </button>
        </form>

        <details className="login-demo">
          <summary>Demo accounts</summary>
          <ul>
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.username}>
                <button type="button" className="link-btn" onClick={() => setUsername(a.username)}>{a.username}</button>
                <span className={`badge badge-role-${a.role}`}>{a.role}</span>
                <span className="login-demo-who" title={a.who}>{a.who}</span>
              </li>
            ))}
          </ul>
          <div className="field-hint">The shared demo password is documented in README.md (demo data only).</div>
        </details>
        <div className="login-foot">Session is kept for this browser tab only.</div>
      </div>
    </div>
  );
}
