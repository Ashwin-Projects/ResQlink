import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { ShieldCheck, RefreshCw, FileText, Lock, Truck, Boxes, History } from 'lucide-react';
import { PageHeader, Panel, Badge, LoadingState, ErrorState, EmptyState } from './ui';
import { describeAuditEvent } from './auditFormat';
import { fmtDate, fmtClock, humanize } from './format';

// Operations timeline over allocation_history: rows written only by database
// triggers (append-only; UPDATE / DELETE / TRUNCATE are rejected). This page
// only reads and groups them.
const FEED_LIMIT = 100;
const KIND_ICONS = { request: FileText, reservation: Lock, allocation: Truck, resource: Boxes };
const FILTERS = [['all', 'All'], ['request', 'Request'], ['reservation', 'Lease'], ['allocation', 'Allocation'], ['resource', 'Resource']];

export default function AuditView() {
  const [feed, setFeed] = useState([]);
  const [state, setState] = useState('loading');
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [transitionsOnly, setTransitionsOnly] = useState(false);

  const load = useCallback(async () => {
    setState('loading');
    try {
      const data = await api.getActivityFeed(FEED_LIMIT);
      setFeed(data.feed || []);
      setError(null);
      setState('ready');
    } catch (err) {
      setError(err.message);
      setState('error');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => {
    const c = { all: feed.length };
    feed.forEach(l => { c[l.entity_type] = (c[l.entity_type] || 0) + 1; });
    return c;
  }, [feed]);

  const groups = useMemo(() => {
    const out = [];
    feed
      .filter(l => (filter === 'all' || l.entity_type === filter) && (!transitionsOnly || l.action === 'status_changed'))
      .forEach(l => {
        const day = fmtDate(l.performed_at);
        const g = out[out.length - 1];
        if (g && g.day === day) g.items.push(l); else out.push({ day, items: [l] });
      });
    return out;
  }, [feed, filter, transitionsOnly]);

  return (
    <div>
      <PageHeader
        eyebrow="Operations"
        title="Audit Trail"
        subtitle="Every request, lease, allocation and resource change, written by PostgreSQL triggers into the append-only allocation_history log."
        actions={(
          <>
            <Badge value="tone-green" title="UPDATE, DELETE and TRUNCATE on allocation_history are rejected by triggers"><ShieldCheck size={12} /> Append-only · trigger-protected</Badge>
            <button type="button" className="btn btn-secondary" onClick={load} disabled={state === 'loading'}>
              <RefreshCw size={14} /> Refresh
            </button>
          </>
        )}
      />

      <Panel title="Activity timeline" icon={History}
             subtitle={`Latest ${FEED_LIMIT} entries, newest first`}
             actions={(
               <div className="toolbar">
                 <div className="segmented" role="group" aria-label="Filter by entity">
                   {FILTERS.map(([k, l]) => (
                     <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>
                       {l} <span className="count">{counts[k] || 0}</span>
                     </button>
                   ))}
                 </div>
                 <div className="segmented" role="group" aria-label="Event type">
                   <button type="button" aria-pressed={!transitionsOnly} onClick={() => setTransitionsOnly(false)}>All events</button>
                   <button type="button" aria-pressed={transitionsOnly} onClick={() => setTransitionsOnly(true)}>State transitions</button>
                 </div>
               </div>
             )}>
        {state === 'loading' && <LoadingState label="Loading audit log…" />}
        {state === 'error' && <ErrorState title="Unable to load the audit trail" message={error} onRetry={load} />}
        {state === 'ready' && feed.length === 0 && <EmptyState icon={History} title="No audit entries yet" message="Entries appear as soon as requests, leases, allocations or resources change." />}
        {state === 'ready' && feed.length > 0 && groups.length === 0 && <EmptyState compact title="No entries match the selected filters" />}
        {state === 'ready' && groups.map(g => (
          <div className="audit-day" key={g.day}>
            <div className="audit-day-label">{g.day}</div>
            <ol className="audit-list" aria-label={`Audit entries ${g.day}`}>
              {g.items.map(log => {
                const e = describeAuditEvent(log);
                const Icon = KIND_ICONS[log.entity_type] || History;
                return (
                  <li className="audit-item" key={log.log_id} data-entity={log.entity_type}>
                    <time className="audit-time" dateTime={log.performed_at} title={new Date(log.performed_at).toLocaleString()}>{fmtClock(log.performed_at)}</time>
                    <span className={`audit-icon kind-${log.entity_type}`}><Icon size={14} /></span>
                    <div style={{ minWidth: 0 }}>
                      <div className="audit-head">
                        <span className="audit-title">{e.title}</span>
                        <Badge value={e.isTransition ? 'tone-blue' : 'tone-gray'} dot={false} className="badge-square">{humanize(log.action)}</Badge>
                        <span className="audit-entity" title={log.entity_id}>{e.entity}</span>
                      </div>
                      {e.changes.length > 0 && (
                        <div className="audit-changes">
                          {e.changes.map(c => (
                            <span className="change-chip" key={c.field}><b>{c.field}</b>{c.from} → <span className="to">{c.to}</span></span>
                          ))}
                        </div>
                      )}
                      {e.remarks && <div className="audit-remarks">{e.remarks}</div>}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        ))}
      </Panel>
    </div>
  );
}
