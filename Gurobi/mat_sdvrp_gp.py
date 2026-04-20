"""File contains fundamental framework for CPSat-solved CVRP (constrainted vehicle routing problem).
It concludes only store demands as constraints. Other features will be added sequentially in other files.
Vehicle capacity is set to 87, corresponding to the highest single-store demand in the data"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import gurobipy as gp
from gurobipy import GRB

from data_prep import load_data

def compute_arc_weights_heterogeneous(distances, times, trucks, T, _lambda):
    """Pre-compute arc cost for objective function per truck type"""
    costs, emissions = {}, {}
    for t in T:
        p_km = trucks.loc[t, "cost_km"]
        p_t = trucks.loc[t, "cost_hour"]
        e = trucks.loc[t, "emission_km"]
        for i in distances.index:
            for j in distances.index:
                costs[i,j,t] = p_t*times.loc[i,j] + p_km*distances.loc[i,j]
                emissions[i,j,t] = e*distances.loc[i,j]

    # Normalise both statistics across ALL truck types and arcs
    max_cost = max(costs.values()) if costs else 1
    max_em = max(emissions.values()) if emissions else 1

    weights = {}
    for t in T:
        for i in distances.index:
            for j in distances.index:
                weights[i,j,t] = _lambda*costs[i,j,t]/max_cost + (1-_lambda)*emissions[i,j,t]/max_em
    
    return weights, costs, emissions

def greedy_warm_start(model, x, q, y, V, C, K, A_set, demand, capacity, weights):
    """Nearest-neighbour heuristic to warm-start Gurobi."""
    unserved = {i: demand[i] for i in C}
    routes = []
    current_truck = 0

    while any(v > 0 for v in unserved.values()) and current_truck < len(K):
        route = []
        load = 0
        current = 0  # depot

        while True:
            # Find nearest unserved customer with remaining capacity
            candidates = {
                i: weights[current, i]
                for i in C
                if unserved[i] > 0 and load < capacity
            }
            if not candidates:
                break

            next_node = min(candidates, key=candidates.get)
            deliver = min(unserved[next_node], capacity - load)
            route.append((next_node, deliver))
            load += deliver
            unserved[next_node] -= deliver
            current = next_node

        if route:
            routes.append(route)
        current_truck += 1

    # Set Gurobi start values
    for k, route in enumerate(routes):
        visited = [node for node, _ in route]
        for idx, (node, qty) in enumerate(route):
            y[node, k].Start = 1
            q[node, k].Start = qty
            
            # Depot to first node
            if idx == 0 and (0, node) in A_set:
                x[0, node, k].Start = 1
            
            # Node to node
            if idx < len(route) - 1:
                next_node = route[idx + 1][0]
                if (node, next_node) in A_set:
                    x[node, next_node, k].Start = 1

            # Last node back to depot
            if idx == len(route) - 1 and (node, 0) in A_set:
                x[node, 0, k].Start = 1

    return model

def solve_sdvrp(weekday: str, cost_weight: float, time_limit: int):

    # ----  SET UP PARAMETERS AND STRUCTURE ---- 
    trucks, stores, demands, distances, times = load_data(file_name="PBAS - Data Case AH 2026.xlsx", day=weekday)

    demand = demands["demand"]
    V = list(distances.index) # set of nodes
    C = list(demands.index) # set of stores / customers
    T = list(trucks.index) # set of truck types

    #Hierarchy of truck types allowed at stores
    truck_hierarchy = {"Small": 1, "Rigid": 2, "City": 3, "Euro": 4}
    store_max_truck_level = {}
    for i in C:
        allowed = stores.loc[i, "Max. allowed truck type"]
        store_max_truck_level[i] = truck_hierarchy.get(allowed, 4)
    
    K_t = {}
    total_demand = demand.sum()

    for t in T:
        cap_t = trucks.loc[t, "cap"]
        is_ev = trucks.loc[t, "is_ev"]
        
        if is_ev:
            max_trucks = int(np.ceil(total_demand / cap_t)) + 2
        else:
            t_level = truck_hierarchy.get(t, 4)
            exclusive_stores = [i for i in C if store_max_truck_level[i] == t_level]
            spec_demand = sum(demand[i] for i in exclusive_stores)
            max_trucks = int(np.ceil(spec_demand / cap_t)) + 3
            
            #manual solution for computational power reduction: if there are only 2 'Small' stores, we'll rarely need more than 3-4 'Small' trucks
            #if t == "Small": max_trucks = min(max_trucks, 4)
            #if t == "Rigid": max_trucks = min(max_trucks, 3)
            #if t == "City":  max_trucks = min(max_trucks, 6)

        K_t[t] = list(range(max_trucks))
        print(f"Truck type {t}: Allocated {max_trucks} units.")

    max_cap_for_store = {}
    for i in C:
        allowed_types = [
            t for t in T 
            if trucks.loc[t, "is_ev"] or truck_hierarchy.get(t, 4) <= store_max_truck_level[i]
        ]
        max_cap_for_store[i] = max([trucks.loc[t, "cap"] for t in allowed_types])

    min_visits = {i: int(np.ceil(demand[i]/max_cap_for_store[i])) for i in C}

    weights, costs, emissions = compute_arc_weights_heterogeneous(
        distances=distances,
        times=times,
        trucks = trucks,
        T=T,
        _lambda=cost_weight
    )

    def get_knn_arcs(distances, V, C, k=20):
        """For each node, keep only arcs to its k nearest neighbours.
        Always keep arcs to/from depot."""

        active = set()
        depot = 0

        for i in V:
            if i != depot:
                active.add((depot, i))
                active.add((i, depot))

            neighbours = sorted(
                [j for j in C if j != i], 
                key=lambda j: distances.loc[i,j]
            )[:k]

            for j in neighbours:
                active.add((i,j))
                active.add((j,i))

        return list(active)

    A = get_knn_arcs(distances, V, C)
    # A = [(i,j) for i in V for j in V if i != j]
    A_set = set(A)
    
    model = gp.Model("SDVRP")
    model.setParam("TimeLimit", time_limit)
    model.setParam("LogToConsole", 1)
    model.setParam("MIPFocus", 1)
    model.setParam("Cuts", 2)
    model.setParam("Heuristics", 0.3)
    model.setParam("MIPGap", 0.05)

    # ----  DECISION VARIABLES ---- 
    x = model.addVars([(i, j, k, t) for t in T for k in K_t[t] for (i, j) in A], vtype=GRB.BINARY, name="x")
    y = model.addVars([(i, k, t) for t in T for k in K_t[t] for i in C], vtype=GRB.BINARY, name="y")
    q = model.addVars([(i, k, t) for t in T for k in K_t[t] for i in C], 
                      lb=0, 
                      ub={(i, k, t): min(demand[i], trucks.loc[t, "cap"]) for t in T for k in K_t[t] for i in C}, 
                      vtype=GRB.INTEGER, name="q")
    u = model.addVars([(i, k, t) for t in T for k in K_t[t] for i in C], 
                      lb=0, 
                      ub={(i, k, t): trucks.loc[t, "cap"] for t in T for k in K_t[t] for i in C}, 
                      vtype=GRB.CONTINUOUS, name="u")

    # ----  OBJ FUNC ---- 
    model.setObjective(
        gp.quicksum(weights[i,j,t] * x[i,j,k,t] for t in T for k in K_t[t] for (i,j) in A), GRB.MINIMIZE
    )

    # ---- CONSTRAINTS ---- 

    # Stores receives enough visits to have demand for that day be fulfilled
    for i in C:
        model.addConstr(gp.quicksum(y[i,k,t] for t in T for k in K_t[t]) >= min_visits[i], name=f"min_visits_{i}")

    # Demand exactly fulfilled, allow for split deliveries (SDVRP)
    for i in C:
        model.addConstr(gp.quicksum(q[i,k,t] for t in T for k in K_t[t]) == demand[i], name=f"demand_{i}")

    # Delivery only happens on visited arcs
    for i in C:
        for t in T:
            cap_t = trucks.loc[t, "cap"]
            for k in K_t[t]:
                model.addConstr(q[i,k,t] <= min(demand[i], cap_t) * y[i,k,t], name=f"link_qy_{i}_{k}_{t}")


    # Truck restrictions on stores satisfied
    for i in C:
        for t in T:
            if not trucks.loc[t, "is_ev"]: # Alleen voor diesel trucks checken, want EV's mogen overal komen
                if truck_hierarchy.get(t, 4) > store_max_truck_level[i]:
                    for k in K_t[t]:
                        model.addConstr(y[i,k,t] == 0, name=f"restr_truck_{i}_{k}_{t}")

    # Flow conservation
    for i in C:
        for t in T:
            for k in K_t[t]:
                model.addConstr(gp.quicksum(x[j,i,k,t] for j in V if j != i and (j,i) in A_set) == y[i,k,t], name=f"flow_in_{i}_{k}_{t}")
                model.addConstr(gp.quicksum(x[i,j,k,t] for j in V if j != i and (i,j) in A_set) == y[i,k,t], name=f"flow_out_{i}_{k}_{t}")


    # Each truck departs at most once
    for t in T:
        for k in K_t[t]:
            model.addConstr(gp.quicksum(x[0,j,k,t] for j in C if (0,j) in A_set) <= 1, name=f"one_route_{k}_{t}")
    
    # # Capacity per truck
    # for k in K:
    #     model.addConstr(gp.quicksum(q[i,k] for i in C) <= capacity)

    # Electric vehicle constraint
    # for k in K:
    #   if is_ev == TRUE:
    #       model.addConstr(gp.quicksum(x[i,j,k] for j in V if j != i and (i,j) in A_set * d[i,j] for j in V if j != i and (i,j) in A_set)<= 100)
    
    # MTZ Sub-tour elimination + capacity constr
    for t in T:
        cap_t = trucks.loc[t, "cap"]
        for k in K_t[t]:
            for (i,j) in A:
                if j == 0: continue
                if i == 0:
                    model.addConstr(u[j,k,t] >= q[j,k,t] - cap_t * (1 - x[0,j,k,t]), name=f"mtz_depot_{j}_{k}_{t}")
                else:
                    model.addConstr(u[j,k,t] >= u[i,k,t] + q[j,k,t] - cap_t*(1 - x[i,j,k,t]), name=f"mtz_{i}_{j}_{k}_{t}")

    # Symmetry-breaking for faster computation: use trucks in index order
    for t in T:
        for k_idx in range(len(K_t[t]) - 1):
            k_curr, k_next = K_t[t][k_idx], K_t[t][k_idx+1]
            model.addConstr(gp.quicksum(x[0,j,k_curr,t] for j in C if (0,j) in A_set) >= 
                            gp.quicksum(x[0,j,k_next,t] for j in C if (0,j) in A_set), name=f"sym_{t}_{k_curr}")

    print("Model constructed, starting optimising...")
    #greedy_warm_start(model, x, q, y, V, C, K, A_set, demand, capacity, weights)
    model.optimize()
    
    # ---- EXTRACT SOLUTION ----

    results = []
    status = model.Status

    if status in (GRB.OPTIMAL, GRB.TIME_LIMIT) and model.SolCount > 0:
        print(f"Solve time: {model.Runtime:.4f}s")
        print(f"Objective:  {model.ObjVal:.2f}")
        print(f"Gap:        {model.MIPGap * 100:.2f}%\n")
        
        for t in T:
            for k in K_t[t]:
                # Check of truck (k,t) wordt gebruikt (flow uit depot)
                if sum(round(x[0, j, k, t].X) for j in C if (0, j) in A_set) == 0: 
                    continue 

                route = []
                current = 0
                for _ in range(len(V) + 1):
                    # >>> GEWIJZIGD: Index t toegevoegd aan x
                    next_node = next(
                        (j for j in V if j != current and (current, j) in A_set and round(x[current, j, k, t].X) == 1),
                        None
                    )
                    if next_node is None or next_node == 0:
                        break
                    route.append(next_node)
                    current = next_node

                # >>> GEWIJZIGD: Index t toegevoegd aan q
                deliveries = {i: round(q[i, k, t].X) for i in route}
                results.append((route, deliveries))

    elif model.SolCount == 0:
        print("No feasible solution found within time limit.")

    print(f"Costs : {sum(costs[i, j, t] * x[i, j, k, t].X for t in T for k in K_t[t] for (i, j) in A)}")
    print(f"Emissions : {sum(emissions[i, j, t] * x[i, j, k, t].X for t in T for k in K_t[t] for (i, j) in A)}")

    obj = model.ObjVal if model.SolCount > 0 else None
        
    return results, obj
