"""File contains an outline for a very basic VRP. 
Don't know how useful it will be, mostly used for playing around with google or tools for now."""

import numpy as np
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

from data_prep import load_data, create_dist_matrix, demand_decompose


def create_data_model(demand_df, dist_matrix, capacity=56, n_vehicles=30): # arbitrary capacity and nr of vehicles of 1 type for basic framework
    """Function creates data in single-dictionary form, required for Google OR Tools"""
    store_nrs = dist_matrix.index.tolist()
    distance_matrix = dist_matrix.values.tolist()
    demand_lookup = dict(zip(demand_df["Store"], demand_df["Total demand for this day"]))
    demands = [demand_lookup.get(store, 0) for store in store_nrs] # OBSERVED PROBLEM: Daily demand can outreach vehicle capacity, meaning it is best to split this store into two fictional ones to allow two trucks to separately deal with half of the order

    data = {
        "demands": demands,
        "distances": distance_matrix,
        "vehicle_caps": [capacity] * n_vehicles,
        "n_vehicles": n_vehicles,
        "depot": 0, # position depot as 0-index
        "node_index_to_store": store_nrs
    }

    return data

def basic_vrp_framework(demand_day=0): 

    trucks, dc, df_stores, df_demand, df_distances = load_data("PBAS - Data Case AH 2026.xlsx")
    dist_matrix, time_matrix = create_dist_matrix(df_distances, df_stores)
    monday_demand = demand_decompose(df_demand)[demand_day] # select only Monday for testing purposes

    # Create single-dict-formatted data
    data = create_data_model(demand_df=monday_demand, dist_matrix=dist_matrix)

    # Create data manager
    manager = pywrapcp.RoutingIndexManager(
        len(data["distances"]),
        data["n_vehicles"],
        data["depot"]
    )
    
    # Create routing model
    routing = pywrapcp.RoutingModel(manager)

    # Nested callback functions, GoogleORTools-VRP requires data in callback function format
    def distance_callback(from_index, to_index):
        """Callback to distance matrix"""
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data["distances"][from_node][to_node]

    def demand_callback(from_index):
        """Callback to demand per store"""
        from_node = manager.IndexToNode(from_index)
        return data["demands"][from_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback) 

    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index) # Sets km's as arc cost
    routing.AddDimensionWithVehicleCapacity(
        evaluator_index=demand_callback_index,
        slack_max=0,
        vehicle_capacities=data["vehicle_caps"],
        fix_start_cumul_to_zero=True,
        name="Truck capacity"
    )

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC # Sets minimise total km's as objective function
    )

    solution = routing.SolveWithParameters(search_parameters=search_params) # Exact search

    if solution is None:
        print(f"Solver status: {routing.status()}")
        # Common status codes:
        # 0 = ROUTING_NOT_SOLVED
        # 1 = ROUTING_SUCCESS  
        # 2 = ROUTING_FAIL
        # 3 = ROUTING_FAIL_TIMEOUT
        # 4 = ROUTING_INVALID
        print(f"Total demand: {sum(data['demands'])}")
        print(f"Total capacity: {sum(data['vehicle_caps'])}")

        print(type(dist_matrix[9999][9999]))


    for vehicle_id in range(data["n_vehicles"]):
        index = routing.Start(vehicle_id)
        route = []
        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        print(f"Vehicle {vehicle_id}: {route}")
    
    return data, routing, manager, solution
