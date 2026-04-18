import folium
from data_prep.data_prep_iris import load_data, create_dist_matrix, demand_decompose
from chvrp_model import solve_chvrptw

def run_and_visualize(file_path, day_name="Mon"):
    #Load and prepare data
    trucks, dc, df_stores, df_demand, df_distances = load_data(file_path)
    dist_matrix, time_matrix = create_dist_matrix(df_distances, df_stores)
    
    #Decompose demand and pick the relevant day
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    all_days_demand = demand_decompose(df_demand)
    day_demand = all_days_demand[days.index(day_name)]

    #Solve CHVRPTW
    print(f"Solving for {day_name}...")
    manager, routing, solution, vehicle_map, node_to_store = solve_chvrptw(
        trucks, dc, df_stores, day_demand, dist_matrix, time_matrix
    )

    if not solution:
        print("No solution found!")
        return

    #Visualization logic
    depot_coords = (dc["lat"], dc["long"])
    coord_lookup = df_stores.set_index("Store nr")[["Latitude", "Longitude"]].to_dict("index")

    m = folium.Map(location=depot_coords, zoom_start=10)
    #Different colors for different routes
    colours = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue", "black"]

    #Keep track of performed nodes to identify unperformed ones later
    performed_nodes = []

    for vehicle_id in range(routing.vehicles()):
        index = routing.Start(vehicle_id)
        route_coords = [depot_coords]
        
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            
            #Check if the node corresponds to a store (and not the DC)
            if node_index in node_to_store:
                store_nr = node_to_store[node_index]

                if store_nr != 9999: #Skip DC 
                    performed_nodes.append(store_nr)
                    lat = coord_lookup[store_nr]["Latitude"]
                    lon = coord_lookup[store_nr]["Longitude"]
                    route_coords.append((lat, lon))
                    
                    #Add marker for the store
                    truck_type = vehicle_map[vehicle_id]
                    folium.Marker(
                        [lat, lon],
                        tooltip=f"Store: {store_nr} | Truck: {truck_type}",
                        icon=folium.Icon(color=colours[vehicle_id % len(colours)])
                    ).add_to(m)
                
            index = solution.Value(routing.NextVar(index))

        route_coords.append(depot_coords)

        #Draw the line if the vehicle actually moved
        if len(route_coords) > 2:
            folium.PolyLine(
                route_coords, 
                color=colours[vehicle_id % len(colours)], 
                weight=3,
                opacity=0.8,
                tooltip=f"Route {vehicle_id} ({vehicle_map[vehicle_id]})"
            ).add_to(m)

    #Add depot marker
    folium.Marker(depot_coords, tooltip="Distribution Center", icon=folium.Icon(color="black", icon="home")).add_to(m)

    #Identify stores that cannot be served
    all_stores = [s for s in node_to_store.values() if s != 9999]
    skipped_stores = set(all_stores) - set(performed_nodes)
    
    if skipped_stores:
        print(f"Stores that could not be served: {skipped_stores}")

    output_file = f"routes_{day_name}.html"
    m.save(output_file)
    print(f"Map saved to {output_file}")

if __name__ == "__main__":
    FILE_NAME = "PBAS - Data Case AH 2026.xlsx"
    run_and_visualize(FILE_NAME, day_name="Mon")