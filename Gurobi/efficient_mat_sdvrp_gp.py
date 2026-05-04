"""SDVRP for AH weekly delivery scheduling"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import gurobipy as gp
from gurobipy import GRB

from data_prep.data_prep import load_data


# ---------------------------------------------------------------------------
# Arc weights
# ---------------------------------------------------------------------------
def compute_arc_weights_heterogeneous(distances, times, trucks, T, _lambda):
    """Weighted cost / emission per (arc, truck type). Both terms normalised."""
    costs, emissions = {}, {}
    for t in T:
        p_km = trucks.loc[t, "cost_km"]
        p_t  = trucks.loc[t, "cost_hour"]
        e_km = trucks.loc[t, "emission_km"]
        for i in distances.index:
            for j in distances.index:
                costs[i, j, t]     = p_t * round(times.loc[i, j]/60, 1) + p_km * distances.loc[i, j]
                emissions[i, j, t] = e_km * distances.loc[i, j]

    max_c = max(costs.values()) or 1
    max_e = max(emissions.values()) or 1
    weights = {k: _lambda * costs[k] / max_c + (1 - _lambda) * emissions[k] / max_e
               for k in costs}
    return weights, costs, emissions


# ---------------------------------------------------------------------------
# kNN arc reduction (depot arcs are always kept)
# ---------------------------------------------------------------------------
def get_knn_arcs(distances, V, C, k=20):
    active = set()
    depot = 0
    for i in V:
        if i != depot:
            active.add((depot, i))
            active.add((i, depot))
        nn = sorted([j for j in C if j != i], key=lambda j: distances.loc[i, j])[:k]
        for j in nn:
            active.add((i, j))
            active.add((j, i))
    return list(active)


# ---------------------------------------------------------------------------
# Greedy warm start (nearest-neighbour with split-delivery)
# ---------------------------------------------------------------------------
def run_greedy(C, T, trucks, demand, weights, store_max_level, truck_hierarchy, distances, max_EV_dist=140):
    """Builds routes one truck at a time.

    Truck types are tried largest-capacity non-EV first (efficient & flexible);
    each truck is filled to capacity with the nearest eligible unserved store.
    If a store's demand exceeds the truck's capacity the remainder is left for
    the next truck (split delivery).

    Returns a list of tuples: (truck_type, route_nodes, {store: qty_delivered}).
    """
    unserved = {i: int(demand[i]) for i in C}
    routes = []
    type_order = sorted(T, key=lambda t: -trucks.loc[t, "cap"])

    while sum(unserved.values()) > 0:
        # Find the largest truck type that can still serve *someone*
        chosen_t = None
        for t in type_order:
            t_lvl = truck_hierarchy.get(t, 4)
            is_ev = trucks.loc[t, "is_ev"]
            if any(unserved[i] > 0 and (is_ev or t_lvl <= store_max_level[i]) for i in C):
                chosen_t = t
                break
        if chosen_t is None:
            break  # nothing can serve the remaining stores (should not happen)

        t     = chosen_t
        cap_t = trucks.loc[t, "cap"]
        is_ev = trucks.loc[t, "is_ev"]
        t_lvl = truck_hierarchy.get(t, 4)

        route, deliveries, load, cur, route_dist = [], {}, 0, 0, 0  # 0 = depot
        while load < cap_t:

            cand = [i for i in C if unserved[i] > 0
                    and (is_ev or t_lvl <= store_max_level[i])]
            if not cand:
                break
            nxt = min(cand, key=lambda i: weights[cur, i, t])
            q   = min(unserved[nxt], cap_t - load)
            if is_ev and (route_dist + distances.loc[cur, nxt] + distances.loc[nxt, 0]) > max_EV_dist:
                break  # returning to depot would exceed range

            route.append(nxt)
            route_dist += distances.loc[cur, nxt]
            deliveries[nxt] = q
            load += q
            unserved[nxt] -= q
            cur = nxt

        if not route:
            break
        routes.append((t, route, deliveries))
    return routes


def apply_warm_start(x, y, q, routes, K_t, A_set):
    """Write Start values on the Gurobi vars from the greedy routes."""
    slot = {t: 0 for t in K_t}
    for (t, route, deliveries) in routes:
        if slot[t] >= len(K_t[t]):
            continue  # fleet exhausted for this type — should not happen
        k = K_t[t][slot[t]]
        slot[t] += 1

        prev = 0  # depot
        for node in route:
            y[node, k, t].Start = 1
            q[node, k, t].Start = deliveries[node]
            if (prev, node) in A_set:
                x[prev, node, k, t].Start = 1
            prev = node
        if (prev, 0) in A_set:
            x[prev, 0, k, t].Start = 1


# ---------------------------------------------------------------------------
# Main solve routine
# ---------------------------------------------------------------------------
def solve_sdvrp(weekday: str, cost_weight: float, time_limit: int, max_EV_dist: int = 140):

    # ---- Load data ----
    trucks, stores, demands, distances, times = load_data(
        file_name="PBAS - Data Case AH 2026.xlsx", day=weekday
    )

    demand = demands["demand"]
    V = list(distances.index)   # all nodes incl. depot
    C = list(demands.index)     # customers
    T = list(trucks.index)      # truck types
    T_EV = [t for t in T if trucks.loc[t, "is_ev"]]

    truck_hierarchy = {"Small": 1, "Rigid": 2, "City": 3, "Euro": 4}
    store_max_level = {i: truck_hierarchy.get(stores.loc[i, "Max. allowed truck type"], 4)
                       for i in C}

    weights, costs, emissions = compute_arc_weights_heterogeneous(
        distances, times, trucks, T, _lambda=cost_weight
    )

    # ---- Greedy warm start + fleet sizing ----
    greedy_routes = run_greedy(C, T, trucks, demand, weights,
                               store_max_level, truck_hierarchy, distances)
    greedy_count = {t: 0 for t in T}
    for (t, _, _) in greedy_routes:
        greedy_count[t] += 1

    # Fleet = greedy usage + 2 (feasibility guaranteed, small enough to solve fast)
    K_t = {t: list(range(greedy_count[t] + 2)) for t in T}

    # print(f"\n=== {weekday} ===  |C|={len(C)}  total demand={int(demand.sum())}")
    # print(f"Greedy built {len(greedy_routes)} routes")
    # for t in T:
    #     print(f"  {t:<10s} greedy used={greedy_count[t]:3d}   fleet allocated={len(K_t[t]):3d}")
    # print(f"  TOTAL fleet: {sum(len(v) for v in K_t.values())}\n")

    # ---- Arc set: kNN + all arcs used by greedy (guarantees warm start valid) ----
    A_set = set(get_knn_arcs(distances, V, C, k=10))
    for (_, route, _) in greedy_routes:
        prev = 0
        for node in route:
            A_set.add((prev, node))
            A_set.add((node, prev))
            prev = node
        A_set.add((prev, 0))
        A_set.add((0, prev))
    A = list(A_set)

    # ---- Gurobi model ----
    m = gp.Model("SDVRP")
    m.setParam("LogToConsole", 0)
    m.setParam("TimeLimit", time_limit)
    m.setParam("MIPGap", 0.05)
    m.setParam("MIPFocus", 2)      
    m.setParam("Heuristics", 0.5)
    m.setParam("Cuts", 3)
    m.setParam("RINS", 10)
    m.setParam("Presolve", 2)
    
    x = m.addVars([(i, j, k, t) for t in T for k in K_t[t] for (i, j) in A],
                  vtype=GRB.BINARY, name="x")
    y = m.addVars([(i, k, t) for t in T for k in K_t[t] for i in C],
                  vtype=GRB.BINARY, name="y")
    q = m.addVars([(i, k, t) for t in T for k in K_t[t] for i in C],
                  lb=0,
                  ub={(i, k, t): min(demand[i], trucks.loc[t, "cap"])
                      for t in T for k in K_t[t] for i in C},
                  vtype=GRB.CONTINUOUS, name="q")
    u = m.addVars([(i, k, t) for t in T for k in K_t[t] for i in C],
                  lb=0,
                  ub={(i, k, t): trucks.loc[t, "cap"]
                      for t in T for k in K_t[t] for i in C},
                  vtype=GRB.CONTINUOUS, name="u")

    # ---- Objective ----
    m.setObjective(
        gp.quicksum(weights[i, j, t] * x[i, j, k, t]
                    for t in T for k in K_t[t] for (i, j) in A),
        GRB.MINIMIZE
    )

    # ---- Constraints ----
    # Demand fulfilment (split delivery allowed)
    for i in C:
        m.addConstr(gp.quicksum(q[i, k, t] for t in T for k in K_t[t]) == demand[i],
                    name=f"demand_{i}")

    # Minimum visits  (tightens LP relaxation)
    max_cap_i = {i: max(trucks.loc[t, "cap"] for t in T
                        if trucks.loc[t, "is_ev"]
                        or truck_hierarchy.get(t, 4) <= store_max_level[i])
                 for i in C}
    for i in C:
        m.addConstr(
            gp.quicksum(y[i, k, t] for t in T for k in K_t[t])
            >= int(np.ceil(demand[i] / max_cap_i[i])),
            name=f"min_visits_{i}"
        )

    # Limit SDs
    # for i in C:
    #     m.addConstr(
    #         gp.quicksum(y[i,k,t] for t in T for k in K_t[t]) <= 2 # demand fulfillment spread out over at most 2 routes
    #     )
    
    # for i in C:
    #     for t in T:
    #         for k in K_t[t]:
    #             m.addConstr(u[i,k,t]<=demand[i])
    #             m.addConstr(u[i,k,t]>=q[i,k,t])

    # Link q to y
    for i in C:
        for t in T:
            cap_t = trucks.loc[t, "cap"]
            for k in K_t[t]:
                m.addConstr(q[i, k, t] <= min(demand[i], cap_t) * y[i, k, t],
                            name=f"link_qy_{i}_{k}_{t}")

    # Forbidden store ↔ truck-type combinations
    for i in C:
        for t in T:
            if not trucks.loc[t, "is_ev"] and truck_hierarchy.get(t, 4) > store_max_level[i]:
                for k in K_t[t]:
                    m.addConstr(y[i, k, t] == 0, name=f"restr_{i}_{k}_{t}")

    # Flow conservation
    for i in C:
        for t in T:
            for k in K_t[t]:
                m.addConstr(
                    gp.quicksum(x[j, i, k, t] for j in V if j != i and (j, i) in A_set)
                    == y[i, k, t],
                    name=f"in_{i}_{k}_{t}"
                )
                m.addConstr(
                    gp.quicksum(x[i, j, k, t] for j in V if j != i and (i, j) in A_set)
                    == y[i, k, t],
                    name=f"out_{i}_{k}_{t}"
                )

    # Each truck departs at most once
    for t in T:
        for k in K_t[t]:
            m.addConstr(
                gp.quicksum(x[0, j, k, t] for j in C if (0, j) in A_set) <= 1,
                name=f"one_route_{k}_{t}"
            )

    # MTZ: subtour elimination + capacity
    for t in T:
        cap_t = trucks.loc[t, "cap"]
        for k in K_t[t]:
            for (i, j) in A:
                if j == 0:
                    continue
                if i == 0:
                    m.addConstr(u[j, k, t] >= q[j, k, t] - cap_t * (1 - x[0, j, k, t]),
                                name=f"mtz0_{j}_{k}_{t}")
                else:
                    m.addConstr(u[j, k, t] >= u[i, k, t] + q[j, k, t]
                                - cap_t * (1 - x[i, j, k, t]),
                                name=f"mtz_{i}_{j}_{k}_{t}")
    # EV range constraint: total route distance <= 140 km

    for t in T_EV:
        for k in K_t[t]:
            m.addConstr(
                gp.quicksum(distances.loc[i, j] * x[i, j, k, t] for (i, j) in A if (i, j) in A_set) <= max_EV_dist,
                name=f"ev_range_{k}_{t}"
            )

    # Symmetry breaking: within a truck type, use lower-index trucks first
    for t in T:
        ks = K_t[t]
        for p in range(len(ks) - 1):
            m.addConstr(
                gp.quicksum(x[0, j, ks[p],     t] for j in C if (0, j) in A_set) >=
                gp.quicksum(x[0, j, ks[p + 1], t] for j in C if (0, j) in A_set),
                name=f"sym_{t}_{ks[p]}"
            )

    # ---- Apply warm start, then solve ONCE ----
    apply_warm_start(x, y, q, greedy_routes, K_t, A_set)
    m.update()

    print(f"Starting Gurobi solve for {weekday} with time limit={time_limit}s...")
    m.optimize()
    print(f"Finished solve in {m.Runtime:.1f}s | Obj={m.ObjVal:.4f} | Gap={m.MIPGap * 100:.2f}%")

    # ---- Extract solution ----
    if m.SolCount == 0:
        print("No feasible solution found within time limit.")
        return [], None

    # print(f"\nSolve time: {m.Runtime:.2f}s   Obj: {m.ObjVal:.4f}   Gap: {m.MIPGap * 100:.2f}%")

    results = []
    total_cost = total_em = 0.0
    for t in T:
        for k in K_t[t]:
            if sum(round(x[0, j, k, t].X) for j in C if (0, j) in A_set) == 0:
                continue
            route, cur = [], 0
            trip_km, trip_duration = 0, []
            for _ in range(len(V) + 1):
                nxt = next((j for j in V if j != cur and (cur, j) in A_set
                            and round(x[cur, j, k, t].X) == 1), None)
                if nxt is None or nxt == 0:
                    trip_km += distances.loc[cur, nxt]
                    trip_duration.append(int(times.loc[cur, nxt]))
                    break
                route.append(nxt)
                trip_km += distances.loc[cur, nxt]
                trip_duration.append(int(times.loc[cur, nxt]))
                cur = nxt
            deliveries = {i: round(q[i, k, t].X) for i in route}
            results.append((weekday, route, deliveries, t, trip_km, trip_duration))
            for (i, j) in A:
                if round(x[i, j, k, t].X) == 1:
                    total_cost += costs[i, j, t]
                    total_em   += emissions[i, j, t]

    # print(f"Day cost:     EUR {total_cost:.2f}")
    # print(f"Day emission: {total_em:.2f} kg CO2")
    return results, m.ObjVal, total_cost, total_em
