from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

def solve_chvrptw(trucks, dc, df_stores, day_demand, dist_matrix, time_matrix):
    # 1. Setup Fleet
    vehicle_types = list(trucks.keys())
    num_per_type = 10 
    vehicle_capacities = []
    vehicle_map = {}

    for t_type in vehicle_types:
        for _ in range(num_per_type):
            v_id = len(vehicle_capacities)
            vehicle_capacities.append(trucks[t_type]['cap'])
            vehicle_map[v_id] = t_type

    manager = pywrapcp.RoutingIndexManager(len(dist_matrix), len(vehicle_capacities), 0)
    routing = pywrapcp.RoutingModel(manager)

    # 2. Distance Callback
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(dist_matrix.iloc[from_node, to_node])

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # 3. Capacity Constraint
    demand_map = day_demand.set_index("Store")["Total demand for this day"].to_dict()
    node_to_store_id = list(dist_matrix.index)

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        store_id = node_to_store_id[from_node]
        return int(demand_map.get(store_id, 0)) if store_id != 9999 else 0

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(demand_callback_index, 0, vehicle_capacities, True, "Capacity")

    # 4. Time Window Constraint
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(time_matrix.iloc[from_node, to_node])

    time_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(time_callback_index, 60, 1440, False, "Time")
    time_dimension = routing.GetDimensionOrDie("Time")

    for i in range(len(df_stores)):
        index = manager.NodeToIndex(i)
        time_dimension.CumulVar(index).SetRange(
            int(df_stores.iloc[i]['open_min']), 
            int(df_stores.iloc[i]['close_min'])
        )

    # 5. Location Requirements
    for i in range(len(df_stores)):
        max_truck = df_stores.iloc[i]['Max. allowed truck type']
        index = manager.NodeToIndex(i)
        for v_id, t_type in vehicle_map.items():
            if trucks[t_type]['cap'] > trucks[max_truck]['cap']:
                routing.VehicleVar(index).RemoveValue(v_id)

    # 6. Solve
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    solution = routing.SolveWithParameters(search_parameters)
    
    # Create the mapping needed for the visualizer
    node_to_store = {i: node_to_store_id[i] for i in range(len(node_to_store_id))}
    
    return manager, routing, solution, vehicle_map, node_to_store