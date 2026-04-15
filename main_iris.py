import folium
from data_prep_iris import load_data, create_dist_matrix, demand_decompose
from chvrp_model import solve_chvrptw

def run_and_visualize(file_path, day_name="Mon"):
    # 1. Load and Prepare Data
    trucks, dc, df_stores, df_demand, df_distances = load_data(file_path)
    dist_matrix, time_matrix = create_dist_matrix(df_distances, df_stores)
    
    # Decompose demand and pick the relevant day
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    all_days_demand = demand_decompose(df_demand)
    day_demand = all_days_demand[days.index(day_name)]

    # 2. Solve the CHVRPTW
    print(f"Solving for {day_name}...")
    manager, routing, solution, vehicle_map, node_to_store = solve_chvrptw(
        trucks, dc, df_stores, day_demand, dist_matrix, time_matrix
    )

    if not solution:
        print("No solution found!")
        return
    # Add this line in main.py right after calling the solver:
    node_to_store = {manager.IndexToNode(i): df_stores.iloc[i]['Store nr'] for i in range(len(df_stores))}

    # 3. Visualization logic
    depot_coords = (dc["lat"], dc["long"])
    coord_lookup = df_stores.set_index("Store nr")[["Latitude", "Longitude"]].to_dict("index")

    m = folium.Map(location=depot_coords, zoom_start=10)
    # Different colors for different routes
    colours = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue", "black"]

    for vehicle_id in range(routing.vehicles()):
        index = routing.Start(vehicle_id)
        route_coords = [depot_coords]
        
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            store_nr = node_to_store[node_index]

            if store_nr != 9999: # 9999 is our DC ID
                lat = coord_lookup[store_nr]["Latitude"]
                lon = coord_lookup[store_nr]["Longitude"]
                route_coords.append((lat, lon))
                
                # Add marker for the store
                truck_type = vehicle_map[vehicle_id]
                folium.Marker(
                    [lat, lon],
                    tooltip=f"Store: {store_nr} | Truck: {truck_type}",
                    icon=folium.Icon(color=colours[vehicle_id % len(colours)])
                ).add_to(m)
                
            index = solution.Value(routing.NextVar(index))

        route_coords.append(depot_coords) # Return to DC

        # Draw the line if the vehicle actually moved
        if len(route_coords) > 2:
            folium.PolyLine(
                route_coords, 
                color=colours[vehicle_id % len(colours)], 
                weight=3,
                opacity=0.8,
                tooltip=f"Route {vehicle_id} ({vehicle_map[vehicle_id]})"
            ).add_to(m)

    # Add Depot Marker
    folium.Marker(depot_coords, tooltip="Distribution Center", icon=folium.Icon(color="black", icon="home")).add_to(m)       

    output_file = f"routes_{day_name}.html"
    m.save(output_file)
    print(f"Map saved to {output_file}")

if __name__ == "__main__":
    # Update the filename to your actual Excel file path
    FILE_NAME = "PBAS - Data Case AH 2026.xlsx"
    run_and_visualize(FILE_NAME, day_name="Mon")