# Phase 5: Disaster Scenario & Ground Truth

## Scenario Narrative: Chennai Monsoon Flooding
**Event Date:** November 15, 2026.
**Geography:** South Chennai.

The simulation models a severe cyclone landfall leading to rapid urban flooding. We have divided the affected area into 5 realistic zones with varying levels of impact and resource availability to test the matching engine's ability to handle scarcity and prioritize urgency.

### Affected Zones
1. **Velachery (Zone A):** Low-lying residential area. High density, severe inundation. *Risk: Critical.* Resource-poor.
2. **Sholinganallur (Zone E):** Coastal marshland and IT corridor. Sudden inundation, cutting off roads. *Risk: Critical.* Resource-poor.
3. **Adyar (Zone B):** River adjacent. Overflow causing widespread moderate-to-severe flooding. *Risk: High.*
4. **Tambaram (Zone D):** Southern suburb. Peripheral flooding. *Risk: Medium.*
5. **Guindy (Zone C):** Elevated industrial/commercial hub. Largely safe from severe waterlogging. Serves as a staging area. *Risk: Low.* Resource-rich.

### Dataset Characteristics
- **Shelters:** 1 relief center per zone, with capacities ranging from 100-500.
- **Providers:** 18 distinct providers across government, NGOs, private, and community sectors.
- **Resources:** 50 resources distributed unevenly. The majority of resources (generators, boats, medical supplies, volunteers, vehicles) are concentrated in the Guindy (Zone C) staging area, forcing the engine to evaluate travel across affected zones.
- **Emergency Requests:** 85 requests span the first 48 hours. Most requests are clustered in Velachery and Sholinganallur. Demand outstrips supply, forcing the system to deal with partially fulfillable requests, multi-resource fulfillment, and starvation of low-urgency requests.

### Ground Truth Methodology
A subset of 15 requests (specifically for `boat` resources) is extracted for optimization evaluation. The ground truth determines the theoretically preferred allocations to minimize a combined objective:
`Objective = (Unmet Demand Penalty * Urgency Weight) + Travel Distance Penalty`

This small set is used in Phase 7 to measure the optimality gap between the incremental DB-driven matching engine and an ideal ILP (Integer Linear Programming) solver.
