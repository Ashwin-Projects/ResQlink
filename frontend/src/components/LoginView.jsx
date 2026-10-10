import React, { useState } from 'react';
import {
  LogIn, Loader2, AlertTriangle, ShieldCheck, Eye, EyeOff, UserPlus, LifeBuoy, Boxes, CheckCircle2,
} from 'lucide-react';
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

// The selected role is only checked against the account on the server
// (expected_role); access always follows the account's own role.
const ROLES = [
  { key: 'requester', label: 'Requester', icon: LifeBuoy,
    desc: 'Ask for emergency help (boats, generators, medical supplies…) and follow your requests.' },
  { key: 'owner', label: 'Resource Owner', icon: Boxes,
    desc: 'Register and update the resources your agency or organisation can provide.' },
  { key: 'coordinator', label: 'Coordinator', icon: ShieldCheck,
    desc: 'Match requests to resources, allocate, dispatch and audit. Authorised staff only.' },
];

const OWNER_TYPES = [
  { value: 'government', label: 'Government agency' },
  { value: 'ngo', label: 'NGO' },
  { value: 'private', label: 'Private company' },
  { value: 'community', label: 'Community group' },
];

const USERNAME_RE = /^[A-Za-z0-9._-]{3,64}$/;
const PHONE_RE = /^\+?[0-9][0-9 ()-]{4,18}[0-9]$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function loginErrorMessage(err) {
  switch (err?.kind) {
    case 'auth': return 'Invalid username or password.';
    case 'locked': return 'Too many failed attempts. This account is temporarily locked — try again later.';
    case 'forbidden': return err.message;           // role mismatch / account not active (server text)
    case 'validation': return 'Enter a username (3–64 characters) and a password.';
    case 'network': return err.message;
    default: return err?.message || 'Sign-in failed.';
  }
}

function signupErrorMessage(err) {
  switch (err?.kind) {
    case 'conflict': return 'That username is already taken. Choose another one.';
    case 'forbidden': case 'network': return err.message;
    case 'validation': return Object.keys(err.fieldErrors || {}).length
      ? 'Please correct the highlighted fields.' : (err.message || 'Please check your details.');
    case 'server': return 'Registration failed on the server. Please try again later.';
    default: return err?.message || 'Registration failed.';
  }
}

function RolePicker({ mode, value, onChange, disabled }) {
  return (
    <fieldset className="role-options" disabled={disabled}>
      <legend className="form-label">{mode === 'signin' ? 'Sign in as' : 'Create an account as'}</legend>
      {ROLES.map(({ key, label, desc, icon: Icon }) => (
        <label key={key} className={`role-option${value === key ? ' is-selected' : ''}`}>
          <input type="radio" name={`${mode}-role`} value={key} checked={value === key}
                 onChange={() => onChange(key)} className="sr-only" />
          <Icon size={18} className="role-option-icon" aria-hidden="true" />
          <span className="role-option-text">
            <span className="role-option-label">{label}</span>
            <span className="role-option-desc">{desc}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

function PasswordInput({ id, value, onChange, autoComplete, invalid, describedBy, disabled }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="password-field">
      <input id={id} className="form-input" type={visible ? 'text' : 'password'} autoComplete={autoComplete}
             value={value} onChange={onChange} maxLength={256} disabled={disabled}
             aria-invalid={invalid ? 'true' : undefined} aria-describedby={describedBy} />
      <button type="button" className="password-toggle" onClick={() => setVisible((v) => !v)}
              aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} aria-controls={id}>
        {visible ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}

function FieldError({ id, text }) {
  return text ? <div id={id} className="field-error">{text}</div> : null;
}

const EMPTY_SIGNUP = {
  display_name: '', owner_type: '', username: '', contact_phone: '', contact_email: '', password: '', confirm: '',
};

function validateSignup(role, f) {
  const e = {};
  if (f.display_name.trim().length < 2) e.display_name = role === 'owner' ? 'Enter your organisation’s name.' : 'Enter your full name.';
  if (role === 'owner' && !f.owner_type) e.owner_type = 'Select the organisation type.';
  if (!USERNAME_RE.test(f.username.trim())) e.username = '3–64 characters: letters, digits, dot, underscore or hyphen.';
  if (!PHONE_RE.test(f.contact_phone.trim())) e.contact_phone = 'Enter a phone number (digits, optional +, spaces, - or brackets).';
  if (f.contact_email.trim() && !EMAIL_RE.test(f.contact_email.trim())) e.contact_email = 'Enter a valid email address or leave it empty.';
  if (f.password.length < 10) e.password = 'At least 10 characters.';
  else if (!/[A-Za-z]/.test(f.password) || !/[0-9]/.test(f.password)) e.password = 'Use at least one letter and one digit.';
  else if (f.password.toLowerCase() === f.username.trim().toLowerCase()) e.password = 'The password must differ from the username.';
  if (f.confirm !== f.password) e.confirm = 'Passwords do not match.';
  return e;
}

export default function LoginView({ notice }) {
  const [mode, setMode] = useState('signin');           // signin | signup
  const [role, setRole] = useState('requester');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Sign in
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [signinErrors, setSigninErrors] = useState({});

  // Sign up
  const [form, setForm] = useState(EMPTY_SIGNUP);
  const [fieldErrors, setFieldErrors] = useState({});

  const switchMode = (m) => {
    if (busy) return;
    setMode(m); setError(null); setSuccess(null); setFieldErrors({}); setSigninErrors({});
  };

  const signIn = async (e) => {
    e.preventDefault();
    const v = {};
    if (!USERNAME_RE.test(username.trim())) v.username = 'Enter your username (3–64 characters).';
    if (!password) v.password = 'Enter your password.';
    setSigninErrors(v);
    if (Object.keys(v).length) { setError(null); return; }
    setBusy(true); setError(null); setSuccess(null);
    try {
      const res = await api.login(username.trim(), password, role);
      setPassword('');
      setSession(res);            // App re-renders into the authenticated shell
    } catch (err) {
      setError(loginErrorMessage(err));
      setBusy(false);
    }
  };

  const setField = (k) => (e) => {
    const value = e.target.value;
    setForm((f) => ({ ...f, [k]: value }));
    if (fieldErrors[k]) setFieldErrors((x) => { const n = { ...x }; delete n[k]; return n; });
  };

  const signUp = async (e) => {
    e.preventDefault();
    const v = validateSignup(role, form);
    setFieldErrors(v);
    if (Object.keys(v).length) { setError('Please correct the highlighted fields.'); return; }
    const payload = {
      role, username: form.username.trim(), password: form.password, display_name: form.display_name.trim(),
      contact_phone: form.contact_phone.trim(), contact_email: form.contact_email.trim() || null,
      ...(role === 'owner' ? { owner_type: form.owner_type } : {}),
    };
    setBusy(true); setError(null); setSuccess(null);
    try {
      const res = await api.register(payload);
      if (res.status === 'active') {
        try {                                           // requester: sign straight in
          setSession(await api.login(payload.username, payload.password, res.role));
          return;
        } catch {
          setSuccess(`${res.message} Sign in with your new username.`);
        }
      } else {
        setSuccess(res.message);                        // owner: pending verification
      }
      setUsername(res.username); setPassword(''); setForm(EMPTY_SIGNUP);
      setMode('signin'); setBusy(false);
    } catch (err) {
      const fe = err.fieldErrors || {};
      setFieldErrors(fe);
      setError(signupErrorMessage(err));
      setBusy(false);
    }
  };

  const su = (id) => ({
    id: `signup-${id}`, className: 'form-input', value: form[id], onChange: setField(id), disabled: busy,
    'aria-invalid': fieldErrors[id] ? 'true' : undefined,
    'aria-describedby': fieldErrors[id] ? `signup-${id}-error` : undefined,
  });

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

        <div className="segmented auth-mode" role="group" aria-label="Account">
          <button type="button" aria-pressed={mode === 'signin'} onClick={() => switchMode('signin')}>Sign in</button>
          <button type="button" aria-pressed={mode === 'signup'} onClick={() => switchMode('signup')}>Create account</button>
        </div>

        <h1 className="login-heading">{mode === 'signin' ? 'Sign in to the operations console' : 'Create a ResQLink account'}</h1>
        <p className="login-lead">
          {mode === 'signin'
            ? 'Choose your role. It is checked against your account, and permissions are enforced by the API and by PostgreSQL row-level security.'
            : 'Requesters can start right away. Resource owners are verified by a coordinator before their first sign-in.'}
        </p>

        {notice && !error && !success && (
          <div className="alert alert-info" role="status" data-testid="login-notice"><ShieldCheck size={16} /><div>{notice}</div></div>
        )}
        {success && (
          <div className="alert alert-success" role="status" data-testid="signup-success"><CheckCircle2 size={16} /><div>{success}</div></div>
        )}
        {error && (
          <div className="alert alert-error" role="alert" data-testid="login-error"><AlertTriangle size={16} /><div>{error}</div></div>
        )}

        <RolePicker mode={mode} value={role} onChange={(r) => { setRole(r); setError(null); }} disabled={busy} />

        {mode === 'signin' ? (
          <form onSubmit={signIn} noValidate aria-label="Sign in">
            <div className="form-group">
              <label className="form-label" htmlFor="login-username">Username</label>
              <input id="login-username" className="form-input" autoComplete="username" autoFocus disabled={busy}
                     value={username} onChange={(e) => setUsername(e.target.value)} maxLength={64}
                     aria-invalid={signinErrors.username ? 'true' : undefined}
                     aria-describedby={signinErrors.username ? 'login-username-error' : undefined} />
              <FieldError id="login-username-error" text={signinErrors.username} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="login-password">Password</label>
              <PasswordInput id="login-password" autoComplete="current-password" value={password} disabled={busy}
                             onChange={(e) => setPassword(e.target.value)} invalid={!!signinErrors.password}
                             describedBy={signinErrors.password ? 'login-password-error' : undefined} />
              <FieldError id="login-password-error" text={signinErrors.password} />
            </div>
            <button type="submit" className="btn btn-lg btn-block" disabled={busy}>
              {busy ? <Loader2 size={16} className="spin" /> : <LogIn size={16} />}
              <span>{busy ? 'Signing in…' : `Sign in as ${ROLES.find((r) => r.key === role).label}`}</span>
            </button>
          </form>
        ) : role === 'coordinator' ? (
          <div className="alert alert-info" role="note" data-testid="coordinator-signup-note">
            <ShieldCheck size={16} />
            <div>
              Coordinator accounts cannot be created by sign-up. Coordinator access is granted by an administrator
              to authorised emergency-management staff. If you already have one, use <strong>Sign in</strong>.
            </div>
          </div>
        ) : (
          <form onSubmit={signUp} noValidate aria-label="Create account">
            <div className="form-group">
              <label className="form-label" htmlFor="signup-display_name">{role === 'owner' ? 'Organisation name' : 'Full name'}</label>
              <input {...su('display_name')} autoComplete={role === 'owner' ? 'organization' : 'name'} maxLength={150} />
              <FieldError id="signup-display_name-error" text={fieldErrors.display_name} />
            </div>
            {role === 'owner' && (
              <div className="form-group">
                <label className="form-label" htmlFor="signup-owner_type">Organisation type</label>
                <select {...su('owner_type')} className="form-select">
                  <option value="">Select…</option>
                  {OWNER_TYPES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <FieldError id="signup-owner_type-error" text={fieldErrors.owner_type} />
              </div>
            )}
            <div className="form-group">
              <label className="form-label" htmlFor="signup-username">Username</label>
              <input {...su('username')} autoComplete="username" maxLength={64} />
              {fieldErrors.username
                ? <FieldError id="signup-username-error" text={fieldErrors.username} />
                : <div className="field-hint">Letters, digits, dot, underscore or hyphen; stored in lowercase.</div>}
            </div>
            <div className="form-row-2">
              <div className="form-group">
                <label className="form-label" htmlFor="signup-contact_phone">Phone</label>
                <input {...su('contact_phone')} type="tel" autoComplete="tel" maxLength={20} />
                <FieldError id="signup-contact_phone-error" text={fieldErrors.contact_phone} />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="signup-contact_email">Email <span className="text-3">(optional)</span></label>
                <input {...su('contact_email')} type="email" autoComplete="email" maxLength={150} />
                <FieldError id="signup-contact_email-error" text={fieldErrors.contact_email} />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="signup-password">Password</label>
              <PasswordInput id="signup-password" autoComplete="new-password" value={form.password} disabled={busy}
                             onChange={setField('password')} invalid={!!fieldErrors.password}
                             describedBy={fieldErrors.password ? 'signup-password-error' : 'signup-password-hint'} />
              {fieldErrors.password
                ? <FieldError id="signup-password-error" text={fieldErrors.password} />
                : <div id="signup-password-hint" className="field-hint">At least 10 characters with a letter and a digit.</div>}
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="signup-confirm">Confirm password</label>
              <PasswordInput id="signup-confirm" autoComplete="new-password" value={form.confirm} disabled={busy}
                             onChange={setField('confirm')} invalid={!!fieldErrors.confirm}
                             describedBy={fieldErrors.confirm ? 'signup-confirm-error' : undefined} />
              <FieldError id="signup-confirm-error" text={fieldErrors.confirm} />
            </div>
            <button type="submit" className="btn btn-lg btn-block" disabled={busy}>
              {busy ? <Loader2 size={16} className="spin" /> : <UserPlus size={16} />}
              <span>{busy ? 'Creating account…' : `Create ${ROLES.find((r) => r.key === role).label} account`}</span>
            </button>
          </form>
        )}

        <details className="login-demo">
          <summary>Demo accounts</summary>
          <ul>
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.username}>
                <button type="button" className="link-btn"
                        onClick={() => { switchMode('signin'); setUsername(a.username); setRole(a.role); }}>{a.username}</button>
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
