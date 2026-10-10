import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { BarChart3, Database, Award, Info, Scale, Layers, RefreshCw, FileJson } from 'lucide-react';
import { PageHeader, Panel, Badge, LoadingState, ErrorState, EmptyState, KeyValue } from './ui';
import { humanize } from './format';

// Evaluation results as returned by GET /api/v1/evaluation/results.
//  * MEASURED  — read by the API from evaluation/results/*.json and
//                scenario/ground_truth.json (outputs of the evaluation suite).
//  * REFERENCE — values written directly in backend/app/api/endpoints_evaluation.py
//                (scenario_metadata, ablations); they are not produced by an
//                evaluation run and are labelled as such.
// Nothing is computed, rounded up or substituted on this page.

const n = (v, d = 2) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));

function Measured() { return <Badge value="tone-green" title="Read from evaluation output files">Measured</Badge>; }
function Reference() { return <Badge value="tone-amber" title="Static values defined in the API code, not produced by an evaluation run">Static reference</Badge>; }

function Bar({ value, max, tone = 'blue' }) {
  const w = max > 0 ? Math.max(0, Math.min(100, (Number(value) / max) * 100)) : 0;
  return <div className="qbar" style={{ width: '100%', maxWidth: 220 }}><span className={`tone-${tone}`} style={{ width: `${w}%` }} /></div>;
}

function SummaryTable({ summary }) {
  const configs = Object.entries(summary || {});
  if (!configs.length) return <EmptyState compact title="No summary results" message="evaluation/results/summary.json is empty or missing." />;
  const maxRows = Math.max(...configs.map(([, m]) => Number(m.rows_evaluated) || 0));
  const maxCov = 100;
  return (
    <div className="table-container">
      <table className="data-table" aria-label="Summary results">
        <thead>
          <tr><th>Configuration</th><th>Coverage</th><th className="right">Latency p50 / p95 / p99</th><th>Rows evaluated</th><th className="right">Double allocations</th></tr>
        </thead>
        <tbody>
          {configs.map(([name, m]) => (
            <tr key={name}>
              <td className="cell-main">{humanize(name)}</td>
              <td><div className="num">{n(m.coverage_percent)}%</div><Bar value={m.coverage_percent} max={maxCov} tone="green" /></td>
              <td className="right num nowrap">{n(m.latency_ms?.p50)} / {n(m.latency_ms?.p95)} / {n(m.latency_ms?.p99)} ms</td>
              <td><div className="num">{n(m.rows_evaluated, 0)}</div><Bar value={m.rows_evaluated} max={maxRows} tone="amber" /></td>
              <td className="right num">{n(m.double_allocations, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScalabilityTables({ scalability }) {
  const sizes = Object.values(scalability || {});
  if (!sizes.length) return <EmptyState compact title="No scalability results" message="evaluation/results/scalability.json is empty or missing." />;
  return sizes.map(s => (
    <div key={s.size} style={{ marginBottom: 14 }}>
      <div className="section-title">{n(s.size, 0)} requests · {s.results?.length || 0} seed(s)</div>
      <div className="table-container">
        <table className="data-table table-compact" aria-label={`Scalability ${s.size}`}>
          <thead>
            <tr><th>Seed</th><th className="right">Run time</th><th className="right">Coverage</th><th className="right">Full coverage</th><th className="right">Rows scanned</th><th className="right">p95 latency</th><th className="right">Double alloc.</th><th className="right">Stale match rate</th></tr>
          </thead>
          <tbody>
            {(s.results || []).map(r => {
              const m = r.metrics || {};
              return (
                <tr key={r.seed}>
                  <td className="num">{r.seed}</td>
                  <td className="right num">{n(r.time_seconds, 3)} s</td>
                  <td className="right num">{n(m.coverage_percent)}%</td>
                  <td className="right num">{n(m.full_coverage_percent)}%</td>
                  <td className="right num">{n(m.db_work?.total_rows_scanned, 0)}</td>
                  <td className="right num">{n(m.latency_ms?.p95)} ms</td>
                  <td className="right num">{n(m.double_allocations, 0)}</td>
                  <td className="right num">{m.stale_resource_behavior ? `${n(m.stale_resource_behavior.stale_match_rate)}%` : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  ));
}

function GroundTruth({ gt }) {
  if (!gt || !Object.keys(gt).length) return <EmptyState compact title="No ground truth loaded" message="scenario/ground_truth.json is empty or missing." />;
  const allocs = Array.isArray(gt.allocations) ? gt.allocations : [];
  const byStatus = allocs.reduce((acc, a) => { acc[a.status] = (acc[a.status] || 0) + 1; return acc; }, {});
  return (
    <>
      <KeyValue items={[
        ['Solver', gt.solver || '—'],
        ['Objective', gt.objective || '—'],
        ['Distance weight', gt.distance_weight_km != null ? `${gt.distance_weight_km} per km` : '—'],
        ['Urgency weights', gt.urgency_weights ? Object.entries(gt.urgency_weights).map(([k, v]) => `${k} ${v}`).join(' · ') : '—'],
        ['Requests in key', String(allocs.length)],
        ['Outcome', Object.entries(byStatus).map(([k, v]) => `${v} ${humanize(k)}`).join(' · ') || '—'],
      ]} />
      {Array.isArray(gt.constraints) && gt.constraints.length > 0 && (
        <>
          <div className="section-title">Constraints</div>
          <div className="chip-row">{gt.constraints.map(c => <span key={c} className="tag">{c}</span>)}</div>
        </>
      )}
    </>
  );
}

export default function EvaluationView() {
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading');
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setState('loading');
    try {
      setData(await api.getEvaluationResults());
      setState('ready'); setError(null);
    } catch (err) {
      setError(err.message); setState('error');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <PageHeader
        eyebrow="Technical / benchmark"
        title="Evaluation"
        subtitle="Results of the offline evaluation suite (evaluation/) as stored in the repository, served unchanged by GET /api/v1/evaluation/results."
        actions={<button type="button" className="btn btn-secondary" onClick={load} disabled={state === 'loading'}><RefreshCw size={14} /> Refresh</button>}
      />

      {state === 'loading' && <Panel><LoadingState label="Loading evaluation results…" /></Panel>}
      {state === 'error' && <ErrorState title="Unable to load evaluation results" message={error} onRetry={load} />}

      {state === 'ready' && data && (
        <div className="stack">
          <div className="alert alert-info">
            <Info size={16} />
            <div className="alert-body">
              <Measured /> values are read from the evaluation output files. <Reference /> values are written directly in the API code
              and are not produced by an evaluation run — treat them as planned / reference figures, not results.
            </div>
          </div>

          <Panel title="Full rescan vs incremental" icon={Scale} subtitle={<span className="provenance"><FileJson size={12} /> evaluation/results/summary.json</span>}
                 actions={<Measured />}>
            <SummaryTable summary={data.summary} />
          </Panel>

          <div className="stack">
            <Panel title="Scalability runs" icon={Layers} subtitle={<span className="provenance"><FileJson size={12} /> evaluation/results/scalability.json</span>}
                   actions={<Measured />}>
              <ScalabilityTables scalability={data.scalability} />
            </Panel>
            <Panel title="ILP ground truth" icon={Award} subtitle={<span className="provenance"><FileJson size={12} /> scenario/ground_truth.json</span>}
                   actions={<Measured />}>
              <GroundTruth gt={data.ground_truth} />
            </Panel>
          </div>

          <Panel title="Ablation configurations" icon={BarChart3}
                 subtitle="Defined in backend/app/api/endpoints_evaluation.py — not produced by the evaluation suite"
                 actions={<Reference />}>
            {data.scenario_metadata && (
              <div className="subtle-box" style={{ marginBottom: 14 }}>
                <KeyValue items={Object.entries(data.scenario_metadata).map(([k, v]) => [humanize(k), String(v)])} />
              </div>
            )}
            {Array.isArray(data.ablations) && data.ablations.length > 0 ? (
              <div className="table-container">
                <table className="data-table" aria-label="Ablation reference values">
                  <thead><tr><th>Configuration</th><th className="right">Unmet demand</th><th className="right">Avg distance</th><th className="right">Tuples scanned</th></tr></thead>
                  <tbody>
                    {data.ablations.map(a => (
                      <tr key={a.config}>
                        <td className="cell-main">{a.config}</td>
                        <td className="right num">{n(a.unmet_demand_qty)}</td>
                        <td className="right num">{n(a.avg_distance_km)} km</td>
                        <td className="right num">{n(a.db_tuples_scanned, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState compact title="No ablation values" />}
          </Panel>

          <div className="provenance"><Database size={12} /> Live operational effects of incremental re-matching (per-change timing, requests re-matched) are shown with real measurements on the Hazard Simulator page.</div>
        </div>
      )}
    </div>
  );
}
