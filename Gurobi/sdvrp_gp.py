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

def compute_arc_weights(distances, times, p_km, p_t, e, _lambda):
    """Pre-compute arc cost for objective function"""

    costs, emissions = {}, {}
    for i in distances.index:
        for j in distances.index:
            costs[i,j] = p_t*times.loc[i,j] + p_km*distances.loc[i,j]
            emissions[i,j] = e*distances.loc[i,j]

    # Normalise both statistics so that the lambdas actually produce a trade-off that is sensible.
    max_cost = max(costs.values())
    max_em = max(emissions.values())

    weights = {}
    for i in distances.index:
        for j in distances.index:
            weights[i,j] = _lambda*costs[i,j]/max_cost + (1-_lambda)*emissions[i,j]/max_em
    
    return weights, costs, emissions

def solve_sdvrp(weekday: str, cost_weight: float, time_limit: int):

    # ----  SET UP PARAMETERS AND STRUCTURE ---- 
    trucks, stores, demands, distances, times = load_data(file_name="PBAS - Data Case AH 2026.xlsx", day=weekday)
    capacity = trucks.loc["Euro", "cap"]

    weights, costs, emissions = compute_arc_weights(
        distances=distances,
        times=times,
        p_km=trucks.loc["Euro", "cost_km"],
        p_t=trucks.loc["Euro", "cost_hour"],
        e=trucks.loc["Euro", "emission_km"],
        _lambda=cost_weight
    )

    demand = demands["demand"]
    V = list(distances.index) # set of nodes
    C = list(demands.index) # set of stores / customers

    min_visits = {i: int(np.ceil(demand[i]/capacity)) for i in C}

    max_trucks = sum(min_visits.values()) # UB on trucks used
    
    K = list(range(max_trucks)) # set of trucks
    A = [(i,j) for i in V for j in V if i != j]
    
    model = gp.Model("SDVRP")
    model.setParam("TimeLimit", time_limit)
    model.setParam("LogToConsole", 1)

    # ----  DECISION VARIABLES ---- 
    x = model.addVars(A, K, vtype=GRB.BINARY, name="x")
    y = model.addVars(C, K, vtype=GRB.BINARY, name="y")
    q = model.addVars([(i, k) for i in C for k in K], lb=0, ub={(i,k): min(demand[i], capacity) for i in C for k in K}, vtype=GRB.INTEGER, name="q",)
    u = model.addVars([(i, k) for i in C for k in K], lb=0, ub=capacity, vtype=GRB.CONTINUOUS, name="u",)

    # ----  OBJ FUNC ---- 
    model.setObjective(
        gp.quicksum(weights[i,j]*x[i,j,k] for (i,j) in A for k in K), GRB.MINIMIZE,
    )

    # ---- CONSTRAINTS ---- 

    # Stores receives enough visits to have demand for that day be fulfilled
    for i in C:
        model.addConstr(gp.quicksum(y[i,k] for k in K) >= min_visits[i], name=f"min_visits_{i}")

    # Demand exactly fulfilled, allow for split deliveries (SDVRP)
    for i in C:
        model.addConstr(gp.quicksum(q[i,k] for k in K) == demand[i], name=f"demand_{i}")

    # Delivery only happens on visited arcs
    for i in C:
        for k in K:
            model.addConstr(q[i,k] <= min(demand[i], capacity)*y[i,k], name=f"link_qy_{i}_{k}")

    # Flow conservation
    for i in C:
        for k in K:
            model.addConstr(gp.quicksum(x[i,j,k] for j in V if j != i) == y[i,k], name=f"flow_in_{i}_{k}")
            model.addConstr(gp.quicksum(x[j,i,k] for j in V if j != i) == y[i,k], name=f"flow_out_{i}_{k}")


    # Each truck departs at most once
    for k in K:
        model.addConstr(gp.quicksum(x[0,j,k] for j in C) <= 1, name=f"one_route_{k}")
    
    # # Capacity per truck
    # for k in K:
    #     model.addConstr(gp.quicksum(q[i,k] for i in C) <= capacity)

    # MTZ Sub-tour elimination + capacity constr
    for k in K:
        for (i,j) in A:
            if j == 0:
                continue
            if i == 0:
                model.addConstr(u[j,k] >= q[j,k] - capacity * (1 - x[0,j,k]), name=f"mtz_depot_{j}_{k}")
            else:
                model.addConstr(u[j,k] >= u[i,k] + q[j,k] - capacity*(1 - x[i,j,k]), name=f"mtz_{i}_{j}_{k}")

    # Symmetry-breaking for faster computation: use trucks in index order
    for k in K[:-1]:
        model.addConstr(gp.quicksum(x[0,j,k] for j in C) >= gp.quicksum(x[0,j,k+1] for j in C), name=f"sym_{k}")

    print("Model constructed, starting optimising...")
    model.optimize()
    
    # ---- EXTRACT SOLUTION ----

    results = []
    status = model.Status

    if status in (GRB.OPTIMAL, GRB.TIME_LIMIT) and model.SolCount > 0:
        print(f"Solve time: {model.Runtime:.4f}s")
        print(f"Objective:  {model.ObjVal:.2f}")
        print(f"Gap:        {model.MIPGap * 100:.2f}%\n")
        
        for k in K:
            if sum(round(x[0,j,k].X) for j in C) == 0: 
                continue # Truck is not used, skip iteration

            route = []
            current = 0
            for _ in range(len(V)+1):
                next_node = next(
                    (j for j in V if j != current and round(x[current,j,k].X) == 1),
                    None
                )
                if next_node is None or next_node == 0:
                    break
                route.append(next_node)
                current = next_node

            deliveries = {i: round(q[i,k].X) for i in route}
            results.append((route, deliveries))

    elif model.SolCount == 0:
        print("No feasible solution found within time limit.")

    print(f"Costs : {sum(costs[i,j]*x[i,j,k].X for (i,j) in A for k in K)}")
    print(f"Emissions : {sum(emissions[i,j]*x[i,j,k].X for (i,j) in A for k in K)}")

    obj = model.ObjVal if model.SolCount > 0 else None
        
    return results, obj
