import json
import math
import csv
import pulp

def calc_dist(lat1, lon1, lat2, lon2):
    """Calculate approximate distance in km between two lat/lon points."""
    return math.hypot(float(lat1) - float(lat2), float(lon1) - float(lon2)) * 111.0

def solve_ilp():
    """Solve the resource allocation problem using Integer Linear Programming."""
    requests = []
    with open('requests.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['resource_type_needed'] == 'boat':
                requests.append(row)
                if len(requests) == 15:
                    break

    resources = []
    with open('resources.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['resource_type'] == 'boat' and float(row['quantity_available']) > 0:
                resources.append(row)

    print(f"Solving ground truth using ILP (PuLP) for {len(requests)} requests and {len(resources)} resources.")

    urgency_weights = {'critical': 1000, 'high': 500, 'medium': 100, 'low': 10}
    distance_weight = 1.0  # weight per km

    N_req = len(requests)
    N_res = len(resources)

    if N_req == 0 or N_res == 0:
        print("No requests or resources for subset. Exiting.")
        return

    # Create ILP problem
    prob = pulp.LpProblem("ResourceAllocation", pulp.LpMinimize)

    # Decision variables: x[i][j] = quantity of resource j assigned to request i
    x = {}
    for i in range(N_req):
        for j in range(N_res):
            max_qty = min(int(float(requests[i]['quantity_requested'])), int(float(resources[j]['quantity_available'])))
            x[(i, j)] = pulp.LpVariable(f"x_{i}_{j}", lowBound=0, upBound=max_qty, cat='Integer')

    # Objective: Minimize weighted unmet demand + travel distance penalty
    # Unmet demand for request i = demand_i - sum_j x_ij
    # Weighted unmet demand = sum_i (unmet_i * urgency_weight_i)
    # Travel distance penalty = sum_ij (x_ij * distance_ij * distance_weight)
    # Total objective = sum_i (demand_i * urgency_weight_i) - sum_ij x_ij * (urgency_weight_i - distance_ij * distance_weight)

    objective_terms = []
    for i in range(N_req):
        demand_i = float(requests[i]['quantity_requested'])
        urgency_w = urgency_weights.get(requests[i]['urgency_level'], 10)
        # Constant term: demand_i * urgency_w (doesn't affect optimization but useful for interpretation)
        # Variable term: -sum_j x_ij * (urgency_w - dist_ij * distance_weight)
        for j in range(N_res):
            dist_ij = calc_dist(requests[i]['lat'], requests[i]['lon'], resources[j]['lat'], resources[j]['lon'])
            coeff = -(urgency_w - dist_ij * distance_weight)
            objective_terms.append(coeff * x[(i, j)])

    prob += pulp.lpSum(objective_terms)

    # Constraint 1: sum(x_ij for all j) <= demand_i for each request i
    for i in range(N_req):
        demand_i = float(requests[i]['quantity_requested'])
        prob += pulp.lpSum(x[(i, j)] for j in range(N_res)) <= demand_i

    # Constraint 2: sum(x_ij for all i) <= supply_j for each resource j
    for j in range(N_res):
        supply_j = float(resources[j]['quantity_available'])
        prob += pulp.lpSum(x[(i, j)] for i in range(N_req)) <= supply_j

    # Solve
    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    print(f"Solver status: {pulp.LpStatus[prob.status]}")

    allocations = []
    if prob.status == pulp.LpStatusOptimal:
        for i in range(N_req):
            req_allocated = 0
            allocs = []
            for j in range(N_res):
                val = pulp.value(x[(i, j)])
                if val and val > 0.5:  # Integer variable, so > 0.5 means 1+
                    qty = int(round(val))
                    allocs.append({"resource_id": resources[j]['resource_id'], "qty": qty})
                    req_allocated += qty

            dem = float(requests[i]['quantity_requested'])
            status = "unfulfilled"
            if req_allocated >= dem:
                status = "fulfilled"
            elif req_allocated > 0:
                status = "partially_fulfilled"

            allocations.append({
                "request_id": requests[i]['request_id'],
                "status": status,
                "allocated_qty": req_allocated,
                "resources_used": allocs
            })
    else:
        print("Optimization failed to find optimal solution.")
        return

    ground_truth = {
        "objective": "Minimize weighted unmet demand + travel distance (ILP with PuLP/CBC)",
        "solver": "PuLP CBC (Integer Linear Programming)",
        "urgency_weights": urgency_weights,
        "distance_weight_km": distance_weight,
        "constraints": ["Resource qty <= available", "Total allocated per request <= requested", "Integer allocations"],
        "allocations": allocations
    }

    with open('ground_truth.json', 'w') as f:
        json.dump(ground_truth, f, indent=2)

    print("Optimization complete. Real ILP optimum generated and saved to ground_truth.json.")

    # Print summary
    total_allocated = sum(a['allocated_qty'] for a in allocations)
    total_demand = sum(float(r['quantity_requested']) for r in requests)
    fulfilled = sum(1 for a in allocations if a['status'] == 'fulfilled')
    partial = sum(1 for a in allocations if a['status'] == 'partially_fulfilled')
    print(f"Summary: {fulfilled} fulfilled, {partial} partially fulfilled, {len(allocations)-fulfilled-partial} unfulfilled")
    print(f"Total allocated: {total_allocated} / {total_demand} demand")

if __name__ == '__main__':
    solve_ilp()