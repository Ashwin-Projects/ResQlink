// Display labels only — allowed VALUES come from GET /api/v1/resources/form-options,
// which mirrors the database CHECK constraints.
export const RESOURCE_TYPE_LABELS = {
  generator: 'Generator',
  boat: 'Rescue Boat',
  medical_supply: 'Medical Supplies',
  shelter_capacity: 'Shelter Capacity',
  volunteer: 'Volunteers',
  vehicle: 'Vehicle',
  other: 'Other',
};
export const MOBILITY_LABELS = { land: 'Land', boat: 'Boat', amphibious: 'Amphibious', air: 'Air' };
export const STATUS_LABELS = {
  available: 'Available', allocated: 'Allocated', in_transit: 'In transit',
  depleted: 'Depleted', maintenance: 'Maintenance', unavailable: 'Unavailable',
};
export const MAX_QTY = 99999999.99; // NUMERIC(10,2)
export const label = (map, v) => map[v] || v;

export function quantityError(text, { required = true } = {}) {
  const t = String(text ?? '').trim();
  if (!t) return required ? 'Enter a quantity.' : null;
  const n = Number(t);
  if (!Number.isFinite(n) || n < 0) return 'Quantity must be a number ≥ 0.';
  if (n > MAX_QTY) return 'Quantity is too large.';
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return 'Use at most 2 decimal places.';
  return null;
}

export function coordinateErrors(lat, lng) {
  const errors = {};
  const hasLat = String(lat ?? '').trim() !== '';
  const hasLng = String(lng ?? '').trim() !== '';
  if (hasLat !== hasLng) errors[hasLat ? 'longitude' : 'latitude'] = 'Enter both latitude and longitude, or leave both blank.';
  else if (hasLat) {
    if (!(Number(lat) >= -90 && Number(lat) <= 90)) errors.latitude = 'Latitude must be between -90 and 90.';
    if (!(Number(lng) >= -180 && Number(lng) <= 180)) errors.longitude = 'Longitude must be between -180 and 180.';
  }
  return errors;
}
