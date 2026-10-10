import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { Boxes, Search, Anchor, Truck, Plane, Plus, RefreshCw, CheckCircle2, X, MapPin } from 'lucide-react';
import ResourceForm from './ResourceForm';
import ResourceEditPanel from './ResourceEditPanel';
import { PageHeader, Panel, Badge, LoadingState, ErrorState, EmptyState, Drawer } from './ui';
import { fmtQty, pct, relativeTime } from './format';
import { RESOURCE_TYPE_LABELS, STATUS_LABELS, MOBILITY_LABELS, label } from './resourceLabels';

// Background refresh so changes made elsewhere (matching leases, allocations,
// other operators) show up without a reload.
const LIST_REFRESH_MS = 15000;
const OUT_OF_SERVICE = ['maintenance', 'unavailable', 'depleted'];

function MobilityCell({ mobility }) {
  const Icon = mobility === 'boat' || mobility === 'amphibious' ? Anchor : mobility === 'air' ? Plane : Truck;
  if (!mobility) return <span className="text-3">—</span>;
  return <span className="chip-row nowrap"><Icon size={14} className="text-3" />{label(MOBILITY_LABELS, mobility)}</span>;
}

export default function ResourceView() {
  const [resources, setResources] = useState([]);
  const [listState, setListState] = useState('loading');
  const [listError, setListError] = useState(null);
  const [options, setOptions] = useState(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [notice, setNotice] = useState(null);
  const [highlight, setHighlight] = useState(() => new Set());

  // Live list from GET /api/v1/resources (PostgreSQL). No fallback data.
  const loadResources = useCallback(async ({ silent = false } = {}) => {
    if (!silent) { setListState('loading'); setListError(null); }
    try {
      setResources(await api.listResourcesLive({ limit: 500 }));
      setListState('ready'); setListError(null);
    } catch (err) {
      setListError(err.message);
      if (!silent) setListState('error');
    }
  }, []);

  useEffect(() => {
    loadResources();
    api.getResourceFormOptions().then(setOptions).catch(err => setOptions({ error: err.message }));
  }, [loadResources]);

  useEffect(() => {
    const t = setInterval(() => { if (document.visibilityState === 'visible') loadResources({ silent: true }); }, LIST_REFRESH_MS);
    return () => clearInterval(t);
  }, [loadResources]);

  const markChanged = (id) => setHighlight(prev => new Set(prev).add(id));

  const handleCreated = async (result) => {
    setShowAdd(false);
    markChanged(result.resource.resource_id);
    setNotice(`Resource ${result.resource.resource_id.substring(0, 8)} added: ${fmtQty(result.resource.quantity_total)} ${result.resource.unit_of_measure} of ${label(RESOURCE_TYPE_LABELS, result.resource.resource_type)} (${result.resource.status}).`);
    await loadResources({ silent: true });
  };
  const handleSaved = async (result) => {
    markChanged(result.resource.resource_id);
    await loadResources({ silent: true });
  };

  const canManage = options && !options.error && options.can_manage;
  const types = options?.resource_types || Object.keys(RESOURCE_TYPE_LABELS);

  const counts = useMemo(() => {
    const c = { all: resources.length, in_use: 0 };
    resources.forEach(r => { c[r.status] = (c[r.status] || 0) + 1; if (r.quantity_in_use > 0) c.in_use += 1; });
    return c;
  }, [resources]);

  const filteredResources = resources.filter(res => {
    const s = search.toLowerCase();
    const matchesSearch = !s || [res.resource_type, res.resource_subtype, res.resource_id, res.owner_name, res.zone_name]
      .some(v => (v || '').toLowerCase().includes(s));
    const matchesStatus = statusFilter === 'all' || (statusFilter === 'in_use' ? res.quantity_in_use > 0 : res.status === statusFilter);
    return matchesSearch && matchesStatus && (typeFilter === 'all' || res.resource_type === typeFilter);
  });

  return (
    <div>
      <PageHeader
        eyebrow="Operations"
        title="Resources"
        subtitle={canManage && options.current_role === 'owner'
          ? 'Your organisation’s inventory. Stock and availability changes are written to the ledger and trigger incremental re-matching.'
          : 'Live inventory with availability, commitments and location. Changes are written to the ledger and trigger incremental re-matching.'}
        actions={(
          <>
            <button type="button" className="btn btn-secondary" onClick={() => loadResources()} disabled={listState === 'loading'}>
              <RefreshCw size={14} /> Refresh
            </button>
            {canManage && (
              <button type="button" className="btn" onClick={() => { setShowAdd(true); setNotice(null); setEditingId(null); }} aria-expanded={showAdd}>
                <Plus size={14} /> Add Resource
              </button>
            )}
          </>
        )}
      />

      {notice && (
        <div className="alert alert-success" role="status">
          <CheckCircle2 size={16} /><div className="alert-body">{notice}</div>
          <button type="button" className="btn btn-ghost btn-sm btn-icon" aria-label="Dismiss" onClick={() => setNotice(null)}><X size={12} /></button>
        </div>
      )}
      {options?.error && <ErrorState compact title="Could not load form options" message={options.error} />}

      <Drawer open={showAdd && !!canManage} onClose={() => setShowAdd(false)} labelledBy="add-resource-title">
        <ResourceForm options={options} onCreated={handleCreated} onCancel={() => setShowAdd(false)} />
      </Drawer>
      <Drawer open={!!editingId && !!options && !options.error} onClose={() => setEditingId(null)} labelledBy="edit-resource-title">
        <ResourceEditPanel key={editingId} resourceId={editingId} options={options}
                           onClose={() => setEditingId(null)} onSaved={handleSaved} />
      </Drawer>

      <Panel flush icon={Boxes} title="Inventory"
             subtitle={<>Live from <code>resources</code> · most recently updated first · auto-refresh every {LIST_REFRESH_MS / 1000}s
               {listState === 'ready' && listError && <span style={{ color: '#ff8b8b' }}> · last refresh failed, showing previous data</span>}</>}
             actions={(
               <div className="toolbar">
                 <div className="segmented" role="group" aria-label="Filter by availability">
                   {[['all', 'All'], ['available', 'Available'], ['in_use', 'In use'], ['maintenance', 'Maintenance'], ['unavailable', 'Unavailable'], ['depleted', 'Depleted']].map(([k, l]) => (
                     <button key={k} type="button" aria-pressed={statusFilter === k} onClick={() => setStatusFilter(k)}>
                       {l} <span className="count">{counts[k] || 0}</span>
                     </button>
                   ))}
                 </div>
                 <div className="input-with-icon">
                   <Search size={14} className="input-icon" />
                   <input type="text" className="form-input" placeholder="Search type, owner, zone, ID…" aria-label="Search resources"
                          value={search} onChange={e => setSearch(e.target.value)} style={{ width: 230 }} />
                 </div>
                 <select className="form-select" aria-label="Filter by type" value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
                   <option value="all">All types</option>
                   {types.map(t => <option key={t} value={t}>{label(RESOURCE_TYPE_LABELS, t)}</option>)}
                 </select>
               </div>
             )}>
        {listState === 'loading' && <LoadingState label="Loading inventory…" />}
        {listState === 'error' && <ErrorState title="Unable to load resources" message={`Could not load resources. ${listError || ''}`} onRetry={() => loadResources()} />}
        {listState === 'ready' && resources.length === 0 && (
          <EmptyState icon={Boxes} title="No resources visible to your role yet"
                      message={canManage ? 'Use "Add Resource" to register one.' : undefined} />
        )}
        {listState === 'ready' && resources.length > 0 && filteredResources.length === 0 && (
          <EmptyState compact title="No resources match the selected filters" />
        )}
        {listState === 'ready' && filteredResources.length > 0 && (
          <div className="table-container">
            <table className="data-table" aria-label="Resource inventory">
              <thead>
                <tr>
                  <th>Resource ID</th>
                  <th>Resource</th>
                  <th>Owner</th>
                  <th>Availability</th>
                  <th>Status</th>
                  <th>Mobility</th>
                  <th>Zone / Location</th>
                  <th>Verified</th>
                  <th className="right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredResources.map((res) => {
                  const rowClass = editingId === res.resource_id ? 'row-selected' : highlight.has(res.resource_id) ? 'row-new'
                    : OUT_OF_SERVICE.includes(res.status) ? 'row-muted' : undefined;
                  return (
                    <tr key={res.resource_id} className={rowClass}>
                      <td className="cell-id" title={res.resource_id}>{res.resource_id.substring(0, 18)}…</td>
                      <td>
                        <div className="cell-main">{label(RESOURCE_TYPE_LABELS, res.resource_type)}</div>
                        <div className="cell-sub">{res.resource_subtype || 'Standard unit'}</div>
                      </td>
                      <td className="text-2">{res.owner_name}</td>
                      <td>
                        <div className="num nowrap">
                          <strong style={{ color: res.quantity_available > 0 ? 'var(--green)' : 'var(--red)' }}>{fmtQty(res.quantity_available)}</strong> / {fmtQty(res.quantity_total)} {res.unit_of_measure}
                        </div>
                        <div className="qbar" aria-hidden="true">
                          <span className="seg-available" style={{ width: `${pct(res.quantity_available, res.quantity_total)}%` }} />
                          <span className="seg-inuse" style={{ width: `${pct(res.quantity_in_use || 0, res.quantity_total)}%` }} />
                        </div>
                        {res.quantity_in_use > 0 && <div className="cell-sub" style={{ color: 'var(--amber)' }}>{fmtQty(res.quantity_in_use)} in use</div>}
                      </td>
                      <td><Badge value={res.status}>{label(STATUS_LABELS, res.status)}</Badge></td>
                      <td><MobilityCell mobility={res.mobility_class} /></td>
                      <td>
                        <div>{res.zone_name}</div>
                        <div className="cell-sub mono nowrap">
                          <MapPin size={11} /> {res.latitude != null ? `${Number(res.latitude).toFixed(4)}, ${Number(res.longitude).toFixed(4)}` : 'N/A'}
                        </div>
                      </td>
                      <td className="cell-sub nowrap" style={{ marginTop: 0 }} title={res.last_verified_at ? new Date(res.last_verified_at).toLocaleString() : undefined}>
                        {res.last_verified_at ? relativeTime(res.last_verified_at) : '—'}
                      </td>
                      <td className="actions">
                        <button type="button" className="btn btn-secondary btn-sm"
                                onClick={() => { setEditingId(res.resource_id); setShowAdd(false); }} aria-pressed={editingId === res.resource_id}>
                          {canManage ? 'Edit' : 'Details'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
