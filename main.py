import folium
from data_prep.data_prep import load_data
from Gurobi.efficient_mat_sdvrp_gp import solve_sdvrp #Pak hier EFFICIENT_MAT voor de claude "verbetering"
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
    truck_type_colours = {
        "Small": "#93C6E0",
        "Rigid": "#4A90D9",
        "City": "#1F5FA6",
        "Euro": "#0D2F6E",
        "EV_small": "#6DBF8A",
        "EV_big": "#1E7A3E"
    }
    _, stores, demands, _, _ = load_data(file_name="PBAS - Data Case AH 2026.xlsx", day=weekday)
    demand = demands["demand"]

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
                tooltip=folium.Tooltip(
                    f"Store: {stores.loc[i, 'Store nr']}<br>"
                    f"Demand: {demand[i]}<br>"
                    f"Max truck: {stores.loc[i, 'Max. allowed truck type']}",
                    sticky=True
                ),
                icon=folium.Icon(
                    color="blue"
                )
            ).add_to(route_map)

    for truck_id, (route, deliveries, truck_type) in enumerate(results):
        print(truck_id, route, deliveries, truck_type)
        route_coords = [depot_coords]
        colour = truck_type_colours.get(truck_type)

        for node in route:
            lat, lon = stores.loc[node, "Latitude"], stores.loc[node, "Longitude"]
            route_coords.append((lat, lon))

        route_coords.append(depot_coords)

        folium.PolyLine(
            route_coords,
            color=colour,
            weight=3,
            opacity=0.8,
            tooltip=folium.Tooltip(
                f"Route {truck_id}<br>"
                f"Type {truck_type}",
                sticky=True
            )
        ).add_to(route_map)
    
    output_file = f"routes_{weekday}.html"
    route_map.save(output_file)
    print(f"Map saved to {output_file}")

if __name__ == "__main__":
    run_and_visualize(weekday="Fri", cost_weight=0.1, time_limit=120)