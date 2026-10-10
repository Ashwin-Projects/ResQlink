import React, { useCallback, useEffect, useState, useRef } from 'react';
import { api } from '../api/client';
import L from 'leaflet';
import { RefreshCw, AlertTriangle } from 'lucide-react';
import { PageHeader } from './ui';
import { RESOURCE_TYPE_LABELS, STATUS_LABELS, label } from './resourceLabels';

// Values interpolated into Leaflet's HTML popups (request descriptions are
// user-submitted) must be escaped.
function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
const v = (x) => (x == null || x === '' ? '—' : escapeHtml(x));
const row = (k, val) => `<div class="map-popup-row"><span>${k}</span><b>${val}</b></div>`;

// Marker palette — the same signal colours as the rest of the UI.
const COLORS = {
  critical: '#f05252', high: '#f0a020', medium: '#4c9aff', low: '#8593a5',
  available: '#2fbf71', unavailable: '#8593a5', shelter: '#22b8cf', hazard: '#f05252',
};

const LAYERS = [
  { key: 'requests', label: 'Requests', swatch: { background: COLORS.critical } },
  { key: 'resources', label: 'Resources', swatch: { background: COLORS.available, borderRadius: 3 } },
  { key: 'shelters', label: 'Shelters', swatch: { borderColor: COLORS.shelter }, ring: true },
  { key: 'hazards', label: 'Hazard areas', hazard: true },
];

export default function MapView() {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);

  const [layers, setLayers] = useState({ resources: [], requests: [], shelters: [], hazards: null });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(true);
  const [visible, setVisible] = useState({ requests: true, resources: true, shelters: true, hazards: true });

  const loadMapData = useCallback(async () => {
    setLoading(true);
    const keys = ['resources', 'requests', 'shelters', 'hazards'];
    const results = await Promise.allSettled([api.getResources(), api.getRequests(), api.getShelters(), api.getHazards()]);
    const next = {}; const errs = {};
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') next[keys[i]] = r.value;
      else { next[keys[i]] = keys[i] === 'hazards' ? null : []; errs[keys[i]] = r.reason?.message || 'Request failed'; }
    });
    // A layer that fails (or that the role may not see) stays empty and is reported — never filled with demo data.
    setLayers(next);
    setErrors(errs);
    setLoading(false);
  }, []);
  useEffect(() => { loadMapData(); }, [loadMapData]);

  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;
    // Default view: the scenario's coastal disaster zone.
    const map = L.map(mapRef.current, { center: [13.06, 80.25], zoom: 12, zoomControl: true });
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      maxZoom: 19,
    }).addTo(map);
    mapInstanceRef.current = map;
    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  // Render layers
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    map.eachLayer((layer) => {
      if (layer instanceof L.Marker || layer instanceof L.GeoJSON || layer instanceof L.CircleMarker) map.removeLayer(layer);
    });

    const { hazards, shelters, resources, requests } = layers;

    if (visible.hazards && hazards && hazards.features) {
      L.geoJSON(hazards, {
        style: { color: COLORS.hazard, weight: 2, fillColor: COLORS.hazard, fillOpacity: 0.18, dashArray: '6 4' },
        onEachFeature: (feature, layer) => {
          const p = feature.properties || {};
          layer.bindPopup(`
            <div class="map-popup-kicker" style="color:${COLORS.hazard}">Hazard area</div>
            <div class="map-popup-title">${v(p.name)}</div>
            ${row('Type', v(p.hazard_type))}
            ${row('Severity', v(p.severity))}`);
        },
      }).addTo(map);
    }

    if (visible.shelters) {
      shelters.forEach(sh => {
        if (sh.lat == null || sh.lng == null) return;
        L.circleMarker([sh.lat, sh.lng], { radius: 7, color: COLORS.shelter, weight: 3, fillColor: '#0b1118', fillOpacity: 0.9 })
          .addTo(map)
          .bindPopup(`
            <div class="map-popup-kicker" style="color:${COLORS.shelter}">Shelter</div>
            <div class="map-popup-title">${v(sh.name)}</div>
            ${row('Occupancy', `${v(sh.capacity_occupied)} / ${v(sh.capacity_total)}`)}
            ${row('Status', v(sh.status))}`);
      });
    }

    if (visible.resources) {
      resources.forEach(res => {
        if (res.lat == null || res.lng == null) return;
        const ok = res.status === 'available';
        L.circleMarker([res.lat, res.lng], { radius: 7, color: '#0b1118', weight: 2, fillColor: ok ? COLORS.available : COLORS.unavailable, fillOpacity: 0.95 })
          .addTo(map)
          .bindPopup(`
            <div class="map-popup-kicker" style="color:${ok ? COLORS.available : COLORS.unavailable}">Resource</div>
            <div class="map-popup-title">${v(label(RESOURCE_TYPE_LABELS, res.resource_type))}${res.resource_subtype ? ` · ${v(res.resource_subtype)}` : ''}</div>
            ${row('Available', `${v(res.quantity_available)} / ${v(res.quantity_total)} ${v(res.unit_of_measure)}`)}
            ${row('Status', v(label(STATUS_LABELS, res.status)))}`);
      });
    }

    if (visible.requests) {
      requests.forEach(req => {
        if (req.lat == null || req.lng == null) return;
        const color = COLORS[req.urgency_level] || COLORS.medium;
        L.circleMarker([req.lat, req.lng], { radius: 10, color: '#e5ebf2', weight: 2, fillColor: color, fillOpacity: 0.95 })
          .addTo(map)
          .bindPopup(`
            <div class="map-popup-kicker" style="color:${color}">Emergency request · ${v(req.urgency_level)}</div>
            <div class="map-popup-title">${v(req.quantity_requested)} × ${v(label(RESOURCE_TYPE_LABELS, req.resource_type_needed))}</div>
            ${row('Fulfilled', `${v(req.quantity_fulfilled)} / ${v(req.quantity_requested)}`)}
            ${row('Status', v(req.status))}
            ${req.description ? `<div class="map-popup-note">${escapeHtml(req.description)}</div>` : ''}`);
      });
    }
  }, [visible, layers]);

  const counts = {
    requests: layers.requests.length,
    resources: layers.resources.length,
    shelters: layers.shelters.length,
    hazards: layers.hazards?.features?.length ?? 0,
  };
  const errorEntries = Object.entries(errors);

  return (
    <div>
      <PageHeader
        eyebrow="Operations"
        title="Live Map"
        subtitle="PostGIS positions of requests, resources and shelters, with the scenario’s hazard areas. Layers follow your role’s visibility."
        actions={(
          <>
            <div className="toolbar" role="group" aria-label="Map layers">
              {LAYERS.map(l => (
                <button key={l.key} type="button" className="layer-toggle" aria-pressed={visible[l.key]}
                        onClick={() => setVisible(s => ({ ...s, [l.key]: !s[l.key] }))}>
                  <span className={`legend-swatch ${l.hazard ? 'hazard' : ''} ${l.ring ? 'ring' : ''}`} style={l.swatch} />
                  {l.label} <span className="count">{counts[l.key]}</span>
                </button>
              ))}
            </div>
            <button type="button" className="btn btn-secondary" onClick={loadMapData} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'spin' : undefined} /> Refresh
            </button>
          </>
        )}
      />

      {errorEntries.length > 0 && (
        <div className="alert alert-warning" role="alert">
          <AlertTriangle size={16} />
          <div className="alert-body">
            <div className="alert-title">Some map layers could not be loaded</div>
            {errorEntries.map(([k, msg]) => <div key={k}>{k}: {msg}</div>)}
          </div>
        </div>
      )}

      <div className="map-wrapper">
        <div ref={mapRef} className="map-canvas" />
        <div className="map-legend" aria-label="Map legend">
          <div className="map-legend-title">Legend</div>
          <div className="legend-row"><span className="legend-swatch" style={{ background: COLORS.critical }} />Request · critical</div>
          <div className="legend-row"><span className="legend-swatch" style={{ background: COLORS.high }} />Request · high</div>
          <div className="legend-row"><span className="legend-swatch" style={{ background: COLORS.medium }} />Request · medium / low</div>
          <div className="legend-row"><span className="legend-swatch small" style={{ background: COLORS.available, borderColor: '#0b1118' }} />Resource · available</div>
          <div className="legend-row"><span className="legend-swatch small" style={{ background: COLORS.unavailable, borderColor: '#0b1118' }} />Resource · not available</div>
          <div className="legend-row"><span className="legend-swatch ring" />Shelter</div>
          <div className="legend-row"><span className="legend-swatch hazard" />Hazard area</div>
        </div>
      </div>
    </div>
  );
}
