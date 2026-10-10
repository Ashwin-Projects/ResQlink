// Shared presentation primitives used by every page, so headers, panels,
// badges and loading / empty / error states look the same everywhere.
import React from 'react';
import { AlertTriangle, Loader2, RefreshCw, Inbox, Check } from 'lucide-react';
import { humanize } from './format';

export function PageHeader({ eyebrow, title, subtitle, actions, children }) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
        {children}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Panel({ title, subtitle, icon: Icon, actions, children, className = '', flush = false, ...rest }) {
  return (
    <section className={`card ${flush ? 'card-flush' : ''} ${className}`.trim()} {...rest}>
      {(title || actions) && (
        <div className="card-header">
          <div className="card-heading">
            {title && <h2 className="card-title">{Icon && <Icon size={16} className="card-title-icon" />}{title}</h2>}
            {subtitle && <div className="card-subtitle">{subtitle}</div>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

// Status / category badge. `value` selects the colour class (badge-<value>).
export function Badge({ value, children, dot = true, title, className = '' }) {
  return (
    <span className={`badge badge-${value} ${dot ? 'badge-dot' : ''} ${className}`.trim()} title={title}>
      {children ?? humanize(value)}
    </span>
  );
}

export function LoadingState({ label = 'Loading…', compact = false }) {
  return (
    <div className={`state state-loading ${compact ? 'state-compact' : ''}`} role="status">
      <Loader2 size={compact ? 14 : 18} className="spin" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ icon: Icon = Inbox, title, message, action, compact = false }) {
  return (
    <div className={`state state-empty ${compact ? 'state-compact' : ''}`}>
      {!compact && <div className="state-icon"><Icon size={20} /></div>}
      <div>
        {title && <div className="state-title">{title}</div>}
        {message && <div className="state-message">{message}</div>}
        {action && <div className="state-action">{action}</div>}
      </div>
    </div>
  );
}

export function ErrorState({ title = 'Something went wrong', message, onRetry, compact = false }) {
  return (
    <div className={`alert alert-error state-error ${compact ? 'state-compact' : ''}`} role="alert">
      <AlertTriangle size={16} className="alert-icon" />
      <div className="alert-body">
        <div className="alert-title">{title}</div>
        {message && <div className="alert-text">{message}</div>}
      </div>
      {onRetry && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          <RefreshCw size={13} /> Retry
        </button>
      )}
    </div>
  );
}

export function StatTile({ label, value, hint, tone = 'neutral', icon: Icon, testId }) {
  return (
    <div className={`stat stat-${tone}`} data-testid={testId}>
      <div className="stat-top">
        <span className="stat-label">{label}</span>
        {Icon && <span className="stat-icon"><Icon size={16} /></span>}
      </div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

// Horizontal step flow (request lifecycle, matching pipeline, re-match pipeline).
export function StepFlow({ steps, label, className = '' }) {
  return (
    <ol className={`stepflow ${className}`} aria-label={label}>
      {steps.map((s, i) => (
        <li key={s.key} className={`stepflow-step is-${s.state}`} aria-current={s.state === 'current' ? 'step' : undefined}>
          <span className="stepflow-marker">{s.state === 'done' ? <Check size={12} /> : i + 1}</span>
          <span className="stepflow-text">
            <span className="stepflow-label">{s.label}</span>
            {(s.meta || s.hint) && <span className="stepflow-meta">{s.meta || s.hint}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

// Proportional bar for counts (status overviews). Segments: [{ key, value, tone, label }]
export function SegmentBar({ segments, total, label }) {
  const sum = total ?? segments.reduce((s, x) => s + (Number(x.value) || 0), 0);
  return (
    <div className="segbar" role="img" aria-label={label}>
      {segments.map(s => (
        <span key={s.key} className={`segbar-seg tone-${s.tone}`}
              style={{ width: `${sum > 0 ? (Number(s.value) / sum) * 100 : 0}%` }} title={`${s.label}: ${s.value}`} />
      ))}
    </div>
  );
}

export function KeyValue({ items, className = '' }) {
  return (
    <dl className={`kv-list ${className}`}>
      {items.filter(Boolean).map(([k, v]) => (
        <React.Fragment key={k}><dt>{k}</dt><dd>{v}</dd></React.Fragment>
      ))}
    </dl>
  );
}

export function Drawer({ open, onClose, labelledBy, children, wide = false }) {
  if (!open) return null;
  return (
    <div className="drawer-root">
      <div className="drawer-backdrop" onClick={onClose} aria-hidden="true" />
      <aside className={`drawer ${wide ? 'drawer-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        {children}
      </aside>
    </div>
  );
}
