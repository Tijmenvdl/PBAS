import folium
from data_prep.data_prep import load_data
from Gurobi.mat_sdvrp_gp import solve_sdvrp
# from Gurobi.alns_sdvrp_gp import solve_alns

def run_and_visualize(weekday: str, cost_weight: float, time_limit: int):
    """Run imported SDVRP model"""

    #Solve model
    print(f"Solving for {weekday}...")
    results, objval = solve_sdvrp(weekday, cost_weight, time_limit)

    if results == []:
        print("No solution found!")
        return None

    #Visualization logic
    colours = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue", "black"]
    _, stores, _, _, _ = load_data(file_name="PBAS - Data Case AH 2026.xlsx", day=weekday)
    depot_coords = (stores.loc[0, "Latitude"], stores.loc[0, "Longitude"])

    route_map = folium.Map(location=depot_coords, zoom_start=13, tiles="CartoDB positron")
    folium.Marker(
                depot_coords,
                tooltip=f"DC",
                icon=folium.Icon(
                    color="red"
                )
            ).add_to(route_map)
    
    for i in range(1, len(stores)):
        lat, lon = stores.loc[i, "Latitude"], stores.loc[i, "Longitude"]
        folium.Marker(
                [lat, lon],
                tooltip=f"Store: {stores.loc[i, 'Store nr']}",
                icon=folium.Icon(
                    color="blue"
                )
            ).add_to(route_map)

    for truck_id, (route, deliveries) in enumerate(results):
        print(truck_id, route, deliveries)
        route_coords = [depot_coords]

        for node in route:
            lat, lon = stores.loc[node, "Latitude"], stores.loc[node, "Longitude"]
            route_coords.append((lat, lon))

        route_coords.append(depot_coords)

        folium.PolyLine(
            route_coords,
            color=colours[truck_id % len(colours)],
            weight=3,
            opacity=0.8,
            tooltip=f"Route {truck_id}"
        ).add_to(route_map)
    
    output_file = f"routes_{weekday}.html"
    route_map.save(output_file)
    print(f"Map saved to {output_file}")

if __name__ == "__main__":
    run_and_visualize(weekday="Mon", cost_weight=0.5, time_limit=120)