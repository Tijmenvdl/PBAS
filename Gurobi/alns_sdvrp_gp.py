"""File contains fundamental framework for CPSat-solved CVRP (constrainted vehicle routing problem).
It concludes only store demands as constraints. Other features will be added sequentially in other files.
Vehicle capacity is set to 87, corresponding to the highest single-store demand in the data"""

import sys
import os
import time
import random
from dataclasses import dataclass, field
from typing import Optional
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

@dataclass
class Route:
    stops: list[int]
    deliveries: dict[int, float]

    def copy(self):
        return Route(list(self.stops), dict(self.deliveries))

@dataclass
class Solution:
    routes: list[Route]
    cost: float = 0.0

    def copy(self):
        return Solution([r.copy() for r in self.routes], self.cost)
    
def route_cost(route: Route, weights: dict, depot: int = 0) -> float:
    if not route.stops:
        return 0.0
    stops = [depot] + route.stops + [depot]
    return sum(weights[stops[i], stops[i+1]] for i in range(len(stops)-1))

def solution_cost(sol: Solution, weights: dict) -> float:
    return sum(route_cost(r, weights) for r in sol.routes)

# Initial solution (greedy nearest-neighbour)
def greedy_initial(C, demand, capacity, weights, depot=0) -> Solution:
    """Build routes with greedy nearest-neightbour + split delivery support."""
    remaining = {i: demand[i] for i in C}
    routes = []

    while any(v > 0 for v in remaining.values()):
        current = depot
        load = 0.0
        route_stops = []
        deliveries = {}

        while True:
            candidates = [i for i in C if remaining[i] > 0]
            if not candidates:
                break

            # Nearest unfinished customer
            nxt = min(candidates, key=lambda i: weights[current, i])
            deliver = min(remaining[nxt], capacity - load)
            if deliver <= 0:
                break

            route_stops.append(nxt)
            deliveries[nxt] = deliver
            remaining[nxt] -= deliver
            load += deliver
            current = nxt

            if load >= capacity:
                break

        if route_stops:
            routes.append(Route(route_stops, deliveries))

    sol = Solution(routes)
    sol.cost = solution_cost(sol, weights)
    return sol

# Destroy operators
def destroy_random(sol: Solution, n_remove: int, rng: random.Random) -> tuple[Solution, list]:
    """Remove n_remove random (customer, route_idx) delivery cunks"""
    s = sol.copy()
    removed = []

    # Collect all (route_idx, stop) pairs
    pool = [(ri, stop) for ri, r in enumerate(s.routes) for stop in r.stops]
    rng.shuffle(pool)

    for ri, stop in pool[:n_remove]:
        route = s.routes[ri]
        if stop not in route.deliveries:
            continue
        removed.append((stop, route.deliveries[stop]))
        del route.deliveries[stop]
        route.stops.remove(stop)

    # Drop empty routes
    s.routes = [r for r in s.routes if r.stops]
    return s, removed

def destroy_worst(sol: Solution, n_remove: int, weights: dict, rng: random.Random) -> tuple[Solution, list]:
    """Remove deliveries with highest marginal arc cost"""
    s = sol.copy()
    removed = []

    def marginal_cost(ri, stop):
        r = s.routes[ri]
        idx = r.stops.index(stop)
        prev_n = r.stops[idx-1] if idx > 0 else 0
        next_n = r.stops[idx+1] if idx < len(r.stops)-1 else 0
        saving = weights[prev_n, stop] + weights[stop, next_n] - weights[prev_n, next_n]
        return saving
    
    pool = [(ri, stop, marginal_cost(ri, stop)) for ri, r in enumerate(s.routes) for stop in r.stops]
    pool.sort(key=lambda x: -x[2])

    # Add slight randomness to avoid determinism
    noise = [(ri, stop, c * (1 + rng.uniform(-0.2, 0.2))) for ri, stop, c in pool]
    noise.sort(key=lambda x: -x[2])

    seen = set()
    for ri, stop, _ in noise:
        if len(removed) >= n_remove:
            break
        if (ri, stop) in seen:
            continue
        seen.add((ri, stop))
        route = s.routes[ri]
        if stop not in route.deliveries:
            continue
        removed.append((stop, route.deliveries[stop]))
        del route.deliveries[stop]
        route.stops.remove(stop)

    s.routes = [r for r in s.routes if r.stops]
    return s, removed

def destroy_related(sol: Solution, n_remove: int, weights: dict, demand: dict, rng: random.Random) -> tuple[Solution, list]:
    """Shaw removal: remove customers similar to a seed (close + similar demand)."""
    s = sol.copy()
    removed = []

    all_stops = [(ri, stop) for ri, r in enumerate(s.routes) for stop in r.stops]
    if not all_stops:
        return s, removed

    seed_ri, seed_stop = rng.choice(all_stops)

    def relatedness(ri, stop):
        d_dist = weights[seed_stop, stop]
        d_dem  = abs(demand[seed_stop] - demand[stop])
        return d_dist + 0.3 * d_dem

    candidates = sorted(
        [(ri, stop) for ri, stop in all_stops if stop != seed_stop],
        key=lambda x: relatedness(x[0], x[1])
    )

    # Seed first
    seed_route = s.routes[seed_ri]
    if seed_stop in seed_route.deliveries:
        removed.append((seed_stop, seed_route.deliveries[seed_stop]))
        del seed_route.deliveries[seed_stop]
        seed_route.stops.remove(seed_stop)

    for ri, stop in candidates[:n_remove - 1]:
        route = s.routes[ri]
        if stop not in route.deliveries:
            continue
        removed.append((stop, route.deliveries[stop]))
        del route.deliveries[stop]
        route.stops.remove(stop)

    s.routes = [r for r in s.routes if r.stops]
    return s, removed

# Repair operators
def _cheapest_insertion_cost(route: Route, stop: int, qty: float, weights: dict, depot=0) -> tuple[float, int]:
    """Return (delta_cost, best_position) for inserting stop at best position"""
    stops = [depot] + route.stops + [depot]
    best_delta = float("inf")
    best_pos = 1

    for pos in range(1, len(stops)):
        prev_n, next_n = stops[pos-1], stops[pos]
        delta = weights[prev_n, stop] + weights[stop, next_n] - weights[prev_n, next_n]
        if delta < best_delta:
            best_delta = delta
            best_pos = pos - 1 # index in route.stops

    return best_delta, best_pos

def repair_greedy(sol: Solution, removed: list, demand: dict, capacity: float, weights: dict, rng: random.Random) -> Solution:
    """Re-insert removed customers using cheapest feasible insertion."""
    s = sol.copy()
    rng.shuffle(removed)

    for stop, qty in removed:
        best_delta = float('inf')
        best_ri = None
        best_pos = None
        best_qty = None

        for ri, route in enumerate(s.routes):
            current_load = sum(route.deliveries.values())
            can_deliver = min(qty, capacity - current_load)
            if can_deliver <= 0:
                continue
            delta, pos = _cheapest_insertion_cost(route, stop, can_deliver, weights)
            if delta < best_delta:
                best_delta = delta
                best_ri = ri
                best_pos = pos
                best_qty = can_deliver

        if best_ri is not None:
            r = s.routes[best_ri]
            r.stops.insert(best_pos, stop)
            r.deliveries[stop] = best_qty
            qty -= best_qty

        # If demand not fully satisfied, open a new route
        if qty > 0:
            deliver = min(qty, capacity)
            new_route = Route([stop], {stop: deliver})
            s.routes.append(new_route)

    s.cost = solution_cost(s, weights)
    return s

def repair_regret2(sol: Solution, removed: list, demand: dict,
                   capacity: float, weights: dict, rng: random.Random) -> Solution:
    """Regret-2 insertion: prioritise customers with largest regret (2nd best - best cost diff)."""
    s = sol.copy()
    uninserted = list(removed)

    while uninserted:
        best_regret = -float('inf')
        chosen_idx = 0
        chosen_ri = None
        chosen_pos = None
        chosen_qty = None

        for idx, (stop, qty) in enumerate(uninserted):
            deltas = []
            for ri, route in enumerate(s.routes):
                current_load = sum(route.deliveries.values())
                can_deliver = min(qty, capacity - current_load)
                if can_deliver <= 0:
                    continue
                delta, pos = _cheapest_insertion_cost(route, stop, can_deliver, weights)
                deltas.append((delta, ri, pos, can_deliver))

            deltas.sort(key=lambda x: x[0])

            if len(deltas) >= 2:
                regret = deltas[1][0] - deltas[0][0]
            elif len(deltas) == 1:
                regret = float('inf')   # only one option — insert now
            else:
                regret = float('inf')   # must open new route

            if regret > best_regret:
                best_regret = regret
                chosen_idx = idx
                if deltas:
                    _, chosen_ri, chosen_pos, chosen_qty = deltas[0]

        stop, qty = uninserted.pop(chosen_idx)

        if chosen_ri is not None:
            r = s.routes[chosen_ri]
            r.stops.insert(chosen_pos, stop)
            r.deliveries[stop] = chosen_qty
            qty -= chosen_qty

        if qty > 0:
            s.routes.append(Route([stop], {stop: min(qty, capacity)}))

    s.cost = solution_cost(s, weights)
    return s

# ALS main loop
SCORE_BEST = 10
SCORE_BETTER = 6
SCORE_ACCEPTED = 3
SCORE_REJECTED = 0

def solve_alns(
        weekday: str,
        cost_weight: float,
        time_limit: int,
        n_remove_frac: float = 0.25, # fraction of customers to remove per iteration
        temp_start: float = 0.05, # SA start temp (as fraction of initial obj)
        cooling: float = 0.9997,
        segment_size: int = 100,
        decay: float = 0.8,
        seed: int = 42,
):
    rng = random.Random(seed)

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
    C = list(demands.index) # set of stores / customers

    # operators
    destroy_ops = [destroy_random, destroy_worst, destroy_related]
    repair_ops = [repair_greedy, repair_regret2]
    d_weights = np.ones(len(destroy_ops))
    r_weights = np.ones(len(repair_ops))
    d_scores = np.ones(len(destroy_ops))
    r_scores = np.ones(len(repair_ops))
    d_uses = np.ones(len(destroy_ops))
    r_uses = np.ones(len(repair_ops))

    # Helpers to call operators with their extra kwargs
    def call_destroy(idx, sol, n_remove):
        op = destroy_ops[idx]
        if op is destroy_random:
            return op(sol, n_remove, rng)
        elif op is destroy_worst:
            return op(sol, n_remove, weights, rng)
        else:
            return op(sol, n_remove, weights, demand, rng)
        
    def call_repair(idx, sol, removed):
        op = repair_ops[idx]
        return op(sol, removed, demand, capacity, weights, rng)
    
    # Build initial solution
    current = greedy_initial(C, demand, capacity, weights)
    best = current.copy()
    print(f"Initial cost: {current.cost:.2f} ({len(current.routes)} routes)")
    
    temperature = temp_start * current.cost
    n_remove = max(1, int(n_remove_frac*len(C)))

    start_time = time.time()
    iteration = 0
    seg_iter = 0

    # Main loop 
    while time.time() - start_time < time_limit:
        # Select operators proportionally to weights
        d_idx = rng.choices(range(len(destroy_ops)),
                             weights=d_weights.tolist())[0]
        r_idx = rng.choices(range(len(repair_ops)),
                             weights=r_weights.tolist())[0]

        destroyed, removed = call_destroy(d_idx, current, n_remove)
        candidate = call_repair(r_idx, destroyed, removed)

        # Simulated annealing acceptance
        delta = candidate.cost - current.cost
        if delta < 0 or rng.random() < np.exp(-delta / max(temperature, 1e-9)):
            score = SCORE_ACCEPTED
            current = candidate
            if candidate.cost < best.cost - 1e-6:
                best = candidate.copy()
                score = SCORE_BEST
                elapsed = time.time() - start_time
                print(f"  iter {iteration:5d} | new best {best.cost:.2f} "
                    #   f"| gap vs greedy {(best.cost/greedy_cost - 1)*100:.1f}%"
                      f" | t={elapsed:.1f}s")
            elif delta < 0:
                score = SCORE_BETTER
        else:
            score = SCORE_REJECTED

        d_scores[d_idx] += score
        r_scores[r_idx] += score
        d_uses[d_idx]   += 1
        r_uses[r_idx]   += 1

        # Cool temperature
        temperature *= cooling
        iteration   += 1
        seg_iter    += 1

        # ── Weight update every segment ──────────────────────────────────
        if seg_iter >= segment_size:
            for i in range(len(d_weights)):
                if d_uses[i] > 0:
                    d_weights[i] = (decay * d_weights[i]
                                    + (1 - decay) * d_scores[i] / d_uses[i])
            for i in range(len(r_weights)):
                if r_uses[i] > 0:
                    r_weights[i] = (decay * r_weights[i]
                                    + (1 - decay) * r_scores[i] / r_uses[i])

            d_scores[:] = 0;  r_scores[:] = 0
            d_uses[:] = 0;    r_uses[:] = 0
            seg_iter = 0

    # ── Extract results in your existing format ───────────────────────────
    elapsed = time.time() - start_time
    print(f"\nDone. {iteration} iterations in {elapsed:.1f}s")
    print(f"Best cost: {best.cost:.2f}")

    results = []
    for route in best.routes:
        if route.stops:
            results.append((route.stops, route.deliveries))

    # Compute cost/emissions breakdown using your existing arc dicts
    total_costs     = sum(costs[i,j]     for r in best.routes
                          for i,j in zip([0]+r.stops, r.stops+[0]))
    total_emissions = sum(emissions[i,j] for r in best.routes
                          for i,j in zip([0]+r.stops, r.stops+[0]))
    print(f"Costs:     {total_costs:.2f}")
    print(f"Emissions: {total_emissions:.4f}")
    # print(results)

    return results, best.cost
