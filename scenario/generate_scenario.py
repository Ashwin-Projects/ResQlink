import json
import uuid
import random
import csv
from datetime import datetime, timedelta
import math

# Use a fixed seed for reproducibility
random.seed(42)

START_TIME = datetime(2026, 11, 15, 8, 0, 0) # Start of disaster simulation

def generate_uuid():
    return str(uuid.uuid4())

def add_noise(lat, lon, max_offset=0.01):
    return [
        lon + random.uniform(-max_offset, max_offset),
        lat + random.uniform(-max_offset, max_offset)
    ]

# 1. ZONES
zones = [
    {"name": "Velachery", "type": "ward", "lat": 12.9815, "lon": 80.2180, "risk": "critical", "desc": "Low-lying, severe flooding, resource-poor"},
    {"name": "Adyar", "type": "ward", "lat": 13.0033, "lon": 80.2566, "risk": "high", "desc": "River adjacent, moderate flooding"},
    {"name": "Guindy", "type": "ward", "lat": 13.0067, "lon": 80.2206, "risk": "low", "desc": "Elevated, resource-rich staging area"},
    {"name": "Tambaram", "type": "ward", "lat": 12.9229, "lon": 80.1275, "risk": "medium", "desc": "Southern suburb, moderate flooding"},
    {"name": "Sholinganallur", "type": "ward", "lat": 12.9010, "lon": 80.2279, "risk": "critical", "desc": "Coastal marshland, severe flooding, resource-poor"}
]

zone_records = []
for z in zones:
    z['id'] = generate_uuid()
    zone_records.append({
        "zone_id": z['id'],
        "zone_name": z["name"],
        "zone_type": z["type"],
        "risk_level": z["risk"],
        "lat": z["lat"],
        "lon": z["lon"]
    })

# 2. SHELTERS (1 per zone)
shelters = []
for z in zones:
    shelters.append({
        "shelter_id": generate_uuid(),
        "zone_id": z['id'],
        "name": f"{z['name']} Relief Center",
        "capacity_total": random.randint(100, 500),
        "lat": z["lat"] + random.uniform(-0.005, 0.005),
        "lon": z["lon"] + random.uniform(-0.005, 0.005)
    })

# 3. OWNERS (15-20)
owner_types = ['government', 'ngo', 'private', 'community']
owners = []
for i in range(18):
    owners.append({
        "owner_id": generate_uuid(),
        "name": f"Provider {i+1} ({random.choice(['Relief', 'Rescue', 'Logistics', 'Care'])})",
        "owner_type": random.choice(owner_types),
        "contact_phone": f"+919876543{i:03d}"
    })

# 4. RESOURCES (40-60)
resource_types = [
    ('generator', 'units'), 
    ('boat', 'units'), 
    ('medical_supply', 'kits'), 
    ('shelter_capacity', 'headcount'), 
    ('volunteer', 'headcount'), 
    ('vehicle', 'vehicles')
]

resources = []
for i in range(50):
    rtype, uom = random.choice(resource_types)
    # Give Guindy (Zone C) more resources (Resource Rich)
    # Make Velachery (Zone A) and Sholinganallur (Zone E) resource-poor
    zone = random.choices(zones, weights=[10, 20, 50, 20, 10])[0]
    
    qty = random.randint(1, 100) if uom in ('kits', 'headcount') else random.randint(1, 5)
    
    resources.append({
        "resource_id": generate_uuid(),
        "owner_id": random.choice(owners)['owner_id'],
        "current_zone_id": zone['id'],
        "resource_type": rtype,
        "quantity_total": qty,
        "quantity_available": random.randint(0, qty), # some partially/fully depleted
        "unit_of_measure": uom,
        "status": random.choice(['available', 'available', 'available', 'allocated', 'depleted', 'maintenance']),
        "lat": zone['lat'] + random.uniform(-0.015, 0.015),
        "lon": zone['lon'] + random.uniform(-0.015, 0.015)
    })
    if resources[-1]["status"] == "depleted":
        resources[-1]["quantity_available"] = 0
    elif resources[-1]["quantity_available"] == 0:
        resources[-1]["status"] = "depleted"

# 5. EMERGENCY REQUESTS (60-100 over 48 hours)
requests = []
urgency_levels = ['critical', 'high', 'medium', 'low']
requester_types = ['individual', 'shelter_manager', 'government_official', 'ngo_field_worker']

requesters = []
for i in range(30):
    requesters.append({
        "requester_id": generate_uuid(),
        "name": f"Requester {i+1}",
        "requester_type": random.choice(requester_types)
    })

for i in range(85):
    rtype, uom = random.choice(resource_types)
    # Direct more requests to resource-poor, high-risk areas
    zone = random.choices(zones, weights=[40, 20, 5, 10, 40])[0]
    
    qty_req = random.randint(1, 50) if uom in ('kits', 'headcount') else random.randint(1, 10)
    
    # Time spread over 48 hours
    hours_offset = random.uniform(0, 48)
    req_time = START_TIME + timedelta(hours=hours_offset)
    
    requests.append({
        "request_id": generate_uuid(),
        "requester_id": random.choice(requesters)['requester_id'],
        "zone_id": zone['id'],
        "resource_type_needed": rtype,
        "quantity_requested": qty_req,
        "urgency_level": random.choices(urgency_levels, weights=[20, 30, 30, 20])[0],
        "status": "open",
        "lat": zone['lat'] + random.uniform(-0.02, 0.02),
        "lon": zone['lon'] + random.uniform(-0.02, 0.02),
        "requested_at": req_time.isoformat() + "Z"
    })

# Output CSVs
def write_csv(filename, data):
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

write_csv('zones.csv', zone_records)
write_csv('owners.csv', owners)
write_csv('resources.csv', resources)
write_csv('requests.csv', requests)
write_csv('shelters.csv', shelters)
write_csv('requesters.csv', requesters)

# GEOJSON GENERATION
def create_geojson(features):
    return {
        "type": "FeatureCollection",
        "features": features
    }

zone_features = []
for z in zones:
    zone_features.append({
        "type": "Feature",
        "properties": {"zone_id": z['id'], "name": z['name'], "risk": z['risk']},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[z['lon']-0.02, z['lat']-0.02],
                             [z['lon']+0.02, z['lat']-0.02],
                             [z['lon']+0.02, z['lat']+0.02],
                             [z['lon']-0.02, z['lat']+0.02],
                             [z['lon']-0.02, z['lat']-0.02]]]
        }
    })

with open('zones.geojson', 'w') as f:
    json.dump(create_geojson(zone_features), f, indent=2)

hazard_features = [
    {
        "type": "Feature",
        "properties": {"type": "flood", "severity": "critical"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[80.20, 12.97], [80.23, 12.97], [80.23, 12.99], [80.20, 12.99], [80.20, 12.97]]]
        }
    },
    {
        "type": "Feature",
        "properties": {"type": "flood", "severity": "high"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[80.22, 12.89], [80.25, 12.89], [80.25, 12.91], [80.22, 12.91], [80.22, 12.89]]]
        }
    }
]

with open('hazards.geojson', 'w') as f:
    json.dump(create_geojson(hazard_features), f, indent=2)

# GROUND TRUTH LOGIC (for a subset of 15 requests)
subset_requests = [r for r in requests if r['resource_type_needed'] == 'boat'][:15]
subset_resources = [r for r in resources if r['resource_type'] == 'boat' and r['status'] == 'available']

ground_truth = {
    "objective": "Minimize weighted unmet demand + travel distance.",
    "constraints": ["Resource qty <= available", "Total allocated per request <= requested"],
    "allocations": []
}

for req in subset_requests:
    # Greedy mapping favoring proximity and urgency
    candidates = sorted(subset_resources, key=lambda res: math.hypot(res['lat'] - req['lat'], res['lon'] - req['lon']))
    allocated = 0
    allocs = []
    for c in candidates:
        if allocated >= req['quantity_requested']:
            break
        if c['quantity_available'] > 0:
            take = min(c['quantity_available'], req['quantity_requested'] - allocated)
            c['quantity_available'] -= take
            allocated += take
            allocs.append({"resource_id": c['resource_id'], "qty": take})
    ground_truth['allocations'].append({
        "request_id": req['request_id'],
        "status": "fulfilled" if allocated == req['quantity_requested'] else ("partially_fulfilled" if allocated > 0 else "unfulfilled"),
        "allocated_qty": allocated,
        "resources_used": allocs
    })

with open('ground_truth.json', 'w') as f:
    json.dump(ground_truth, f, indent=2)

print("Scenario files generated successfully.")
