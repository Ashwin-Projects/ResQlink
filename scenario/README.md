# ResQLink Phase 5: Scenario & Ground Truth

This directory contains the reproducible, simulated disaster dataset required for testing ResQLink's event-driven matching engine (Phase 7).

## Files Included

- `generate_scenario.py`: The master script to generate the 5 zones, 18 owners, 50 resources, 85 requests, shelters, and GeoJSON boundaries.
- `generate_scale_data.py`: A script to generate synthetic requests at 10k, 100k, and 1M row scale for performance benchmarking.
- `generate_hazard_events.py`: A script to generate expanding hazard polygons to test dynamic reachability.
- `ground_truth.py`: A script demonstrating the ILP-based optimal solver for a 15-request subset.
- `ground_truth.json`: The answer key containing the theoretically optimal allocations for the subset.
- `scenario.md`: The narrative description of the Chennai flood scenario and data distribution.

## Generated Datasets
Run `python generate_scenario.py` to generate or reset the following files deterministically:
- `zones.csv`
- `owners.csv`
- `resources.csv`
- `requests.csv`
- `shelters.csv`
- `requesters.csv`
- `zones.geojson`
- `hazards.geojson`

## Usage
These CSVs and GeoJSONs perfectly match the Phase 2 `schema.sql` terminologies (e.g., `urgency_level` in `critical, high, medium, low`). They can be imported via a simple script or COPY command in Phase 7 to populate the test database.
