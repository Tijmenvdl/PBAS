"""File contains fundamental framework for CPSat-solved CVRP (constrainted vehicle routing problem).
It concludes only store demands as constraints. Other features will be added sequentially in other files.
Vehicle capacity is set to 87, corresponding to the highest single-store demand in the data"""

import sys
import os
import time
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from ortools.sat.python import cp_model

from data_prep import load_data

class ProgressCallback(cp_model.CpSolverSolutionCallback):
    """Prints a compact progress line each time a better solution is found."""

    def __init__(self, trucks, customers, x, q):
        super().__init__()
        self._x = x
        self._q = q
        self._trucks = trucks
        self._customers = customers
        self._start = time.time()
        self._solution_count = 0

    def on_solution_callback(self):
        self._solution_count += 1
        elapsed = time.time() - self._start
        obj = self.objective_value
        bound = self.best_objective_bound
        gap = abs(obj - bound) / max(abs(obj), 1e-9) * 100

        # In on_solution_callback
        trucks_used = sum(
            1 for k in self._trucks
            if any(self.value(self._x[0, j, k]) == 1 for j in self._customers)
        )

        print(
            f"  Solution {self._solution_count:3d} | "
            f"obj: {obj:10.1f} | "
            f"bound: {bound:10.1f} | "
            f"gap: {gap:6.2f}% | "
            f"trucks: {trucks_used} | "
            f"time: {elapsed:6.1f}s"
        )

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
            weights[i,j] = int((_lambda*costs[i,j]/max_cost + (1-_lambda)*emissions[i,j]/max_em)*100) # Scale to integer for ORTOOLS
    
    return weights

def solve_sdvrp(weekday: str, cost_weight: float, time_limit: int):

    # ----  SET UP PARAMETERS AND STRUCTURE ---- 
    trucks, stores, demands, distances, times = load_data(file_name="PBAS - Data Case AH 2026.xlsx", day=weekday)
    capacity = trucks.loc["Euro", "cap"]

    weights = compute_arc_weights(
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
    
    model = cp_model.CpModel()

    # ----  DECISION VARIABLES ---- 
    x = {(i,j,k): model.new_bool_var(f"x_{i}_{j}_{k}") for (i, j) in A for k in K}
    y = {(i,k): model.new_bool_var(f"y_{i}_{k}") for i in C for k in K}
    q = {(i,k): model.new_int_var(0, min(demand[i], capacity), f"q_{i}_{k}") for i in C for k in K}
    # u = {(i,k): model.new_int_var(0, capacity, f"u_{i}_{k}") for i in C for k in K}

    # ----  OBJ FUNC ---- 
    model.minimize(
        sum(weights[i,j]*x[i,j,k] for (i,j) in A for k in K)
    )

    # ---- CONSTRAINTS ---- 

    # Stores receives enough visits to have demand for that day be fulfilled
    for i in C:
        model.add(sum(y[i,k] for k in K) >= min_visits[i])

    # Demand exactly fulfilled, allow for split deliveries (SDVRP)
    for i in C:
        model.add(sum(q[i,k] for k in K) == demand[i])

    # Delivery only happens on visited arcs
    for i in C:
        for k in K:
            model.add(q[i,k] <= min(demand[i], capacity)*y[i,k])

    # Flow conservation
    for i in C:
        for k in K:
            model.add(sum(x[i,j,k] for j in V if j != i) == y[i,k])
            model.add(sum(x[j,i,k] for j in V if j != i) == y[i,k])
    
    # Capacity per truck
    for k in K:
        model.add(sum(q[i,k] for i in C) <= capacity)

    # # MTZ Sub-tour elimination + capacity constr
    # for k in K:
    #     for (i,j) in A:
    #         if j == 0:
    #             continue
    #         if i == 0:
    #             model.add(u[j,k] == q[j,k]).only_enforce_if(x[0,j,k])
    #         else:
    #             model.add(u[j,k] >= u[i,k] + q[j,k] - capacity*(1 - x[i,j,k]))
    
    # # Capacity actually enforced
    # for i in C:
    #     for k in K:
    #         model.add(u[i,k] <= capacity)

    # Circuit constraint: one valid route per truck
    for k in K:
        arcs = []

        # Depot self-loop active iff truck is unused
        depot_self = model.new_bool_var(f"depot_self_{k}")
        model.add(sum(x[0,j,k] for j in C) + depot_self == 1)
        arcs.append((0, 0, depot_self))

        # Customer self-loop active iff truck skips that customer
        for i in C:
            skip = model.new_bool_var(f"skip_{i}_{k}")
            arcs.append((i, i, skip))
            model.add(y[i,k] == 0).only_enforce_if(skip)
            model.add(y[i,k] == 1).only_enforce_if(skip.negated())

        # All travel arcs
        for i in V:
            for j in V:
                if i != j:
                    arcs.append((i, j, x[i,j,k]))

        model.add_circuit(arcs) # This, apparently, forces all routes to be a correct circuit, thereby circumventing the need for slow MTZ subtour eliminiations

        # model.add(depot_self==1).only_enforce_if(
        #     [x[0,j,k].negated() for j in C]
        # )
    
        # model.add(sum(q[i,k] for i in C) <= capacity)

    # Symmetry-breaking for faster computation: use trucks in index order
    for k in K[:-1]:
        model.add(sum(x[0,j,k] for j in C) >= sum(x[0,j,k+1] for j in C))

    print("Model constructed, starting optimising...")
    solver = cp_model.CpSolver()
    solver.parameters.log_search_progress = False
    solver.parameters.max_time_in_seconds = time_limit # Stop looking after 2 minutes
    callback = ProgressCallback(K, C, x, q)
    status_code = solver.solve(model, callback)
    status_name = solver.status_name(status_code)
    print(status_name)

    results = []
    if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"Solve time: {solver.WallTime():.4f}s\n")
        
    for k in K:
        if sum(solver.value(x[0,j,k]) for j in C) == 0: 
            print(k, "check-in")
            continue # Truck is not used, skip iteration
        
        print(k, "progress!")
        route = []
        current = 0
        for _ in range(len(V)+1):
            next_node = next(
                (j for j in V if j != current and solver.value(x[current,j,k]) == 1),
                None
            )
            if next_node is None or next_node == 0:
                break
            route.append(next_node)
            current = next_node

        deliveries = {i: solver.value(q[i,k]) for i in route}
        results.append((route, deliveries))

    obj = solver.objective_value
    # else:
    #     obj = None
        
    return results, obj
