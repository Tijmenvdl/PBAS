import folium
import pandas as pd
from data_prep.data_prep import load_data
from Gurobi.efficient_mat_sdvrp_gp import solve_sdvrp #Pak hier EFFICIENT_MAT voor de claude "verbetering"
# from Gurobi.alns_sdvrp_gp import solve_alns

def run_and_visualize(weekday: str, cost_weight: float, time_limit: int):
    """Run imported SDVRP model"""

    #Solve model
    print(f"Solving for {weekday}...")
    results, objval, total_cost, total_em = solve_sdvrp(weekday, cost_weight, time_limit)

    if results == []:
        print("No solution found!")
        return None

    #Visualization logic
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

    for truck_id, (weekday, route, deliveries, truck_type, trip_km, trip_duration) in enumerate(results):
        # print(results)
        # print(truck_id, route, deliveries, truck_type, trip_km, trip_duration)
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

    df =  pd.DataFrame(results, columns=["Weekday", "Route", "Quantities", "Truck type", "Distance (km)", "Duration (min)"])
    return df, total_cost, total_em


def full_week():
    full_week_results = pd.DataFrame() # Initialise empty frame
    total_cost, total_em = 0, 0
    with pd.ExcelWriter("schedule.xlsx") as writer:
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
            day_result, cost, em = run_and_visualize(weekday=day, cost_weight=0.5, time_limit=60)
            day_result.to_excel(writer, sheet_name=day)
            full_week_results = pd.concat([full_week_results, day_result])
            total_cost += cost
            total_em += em
    print(f"Total cost:     EUR {total_cost:.2f}")
    print(f"Total emission: {total_em:.2f} kg CO2")

    full_week_results.to_excel(writer, sheet_name="Full schedule")
    return full_week_results

if __name__ == "__main__":
    full_week()

print()