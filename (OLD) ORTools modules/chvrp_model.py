from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

def solve_chvrptw(trucks, dc, df_stores, day_demand, dist_matrix, time_matrix):
    #Fleet setup
    vehicle_types = list(trucks.keys())
    num_per_type = 100
    vehicle_capacities = []
    vehicle_map = {}

    for t_type in vehicle_types:
        for _ in range(num_per_type):
            v_id = len(vehicle_capacities)
            vehicle_capacities.append(trucks[t_type]['cap'])
            vehicle_map[v_id] = t_type

    manager = pywrapcp.RoutingIndexManager(len(dist_matrix), len(vehicle_capacities), 0)
    routing = pywrapcp.RoutingModel(manager)

    #Travel time callback
    def travel_time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(time_matrix.iloc[from_node, to_node])

    transit_callback_index = routing.RegisterTransitCallback(travel_time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    #Capacity constraint
    demand_map = day_demand.set_index("Store")["Total demand for this day"].to_dict()
    node_to_store_id = list(dist_matrix.index)

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        store_id = node_to_store_id[from_node]
        return int(demand_map.get(store_id, 0)) if store_id != 9999 else 0

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index, 0, vehicle_capacities, True, "Capacity"
    )

    # #Time windows
    # routing.AddDimension(transit_callback_index, 1440, 1440, False, "Time") # we use 1440 (24h in minutes) as a large number to allow waiting time
    # time_dimension = routing.GetDimensionOrDie("Time")

    # for i in range(len(df_stores)):
    #     index = manager.NodeToIndex(i)
    #     store_id = node_to_store_id[i]
        
    #     if store_id == 9999: # DC has no time window
    #         time_dimension.CumulVar(index).SetRange(0, 1440)
    #     else:
    #         time_dimension.CumulVar(index).SetRange(
    #             int(df_stores.iloc[i]['open_min']), 
    #             int(df_stores.iloc[i]['close_min'])
    #         )

    #Truck type constraints: Enforce max truck type per store
    for i in range(len(df_stores)):
        max_truck_type = df_stores.iloc[i]['Max. allowed truck type']
        print(i, max_truck_type)
        if max_truck_type in trucks:
            max_cap = trucks[max_truck_type]['cap']
            index = manager.NodeToIndex(i+1) # depot is set to node 0!!
            for v_id, t_type in vehicle_map.items():
                if trucks[t_type]['cap'] > max_cap:
                    routing.VehicleVar(index).RemoveValue(v_id)

    #Stores that cannot be served by any truck type should be marked as unperformed with a penalty
    penalty = routing.kNoPenalty
    for i in range(1, len(dist_matrix)):
        routing.AddDisjunction([manager.NodeToIndex(i)], penalty)

    #Solve
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    search_parameters.time_limit.seconds = 30

    solution = routing.SolveWithParameters(search_parameters)
    
    node_to_store = {i: node_to_store_id[i] for i in range(len(node_to_store_id))}
    return manager, routing, solution, vehicle_map, node_to_store