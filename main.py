import folium
import pandas as pd
from Gurobi.efficient_mat_sdvrp_gp import solve_sdvrp #Pak hier EFFICIENT_MAT voor de claude "verbetering"
import matplotlib.pyplot as plt
# from Gurobi.alns_sdvrp_gp import solve_alns
from data_prep.data_prep import load_data, load_extended_store_data


def heuristic_time_stage(results, stores, store_info, service_times, time_matrix):
    """Calculates arrival and service times for the routes from Phase 1"""    
    for truck_id, (weekday, route, deliveries, truck_type, trip_km, trip_duration) in enumerate(results):
        current_time = 480  # Start at 08:00
        previous_node = 0   # Start at DC
        
        print(f"\nTruck {truck_id} ({truck_type}) on {weekday}:")
        
        for store in route:
            # Travel
            travel_time = time_matrix.at[previous_node, store]
            current_time += travel_time
            
            # Opening hours check
            store_nr = stores.loc[store, "Store nr"]
            open_time = store_info[store_nr]['open']
            close_time = store_info[store_nr]['close']
            
            if current_time < open_time:
                print(f"  * Waiting {open_time - current_time:.1f} min for opening.")
                current_time = open_time
            
            # Print arrival
            arrival_h, arrival_m = int(current_time // 60), int(current_time % 60)
            print(f"  - Store {store}: Arrival at {arrival_h:02d}:{arrival_m:02d}")
            
            if current_time > close_time:
                print(f"  ALARM: Too late at store {store}! (Closes: {close_time//60:02d}:00)")

            # Service
            current_time += service_times.get(truck_type, 30)
            previous_node = store

def run_and_visualize(weekday: str, cost_weight: float, time_limit: int):
    """Run imported SDVRP model and calculate schedule"""
    # 1. Solve Phase 1
    results, objval, total_cost, total_em = solve_sdvrp(weekday, cost_weight, time_limit)

    if not results:
        print(f"No solution found for {weekday}!")
        return None, 0, 0

    # 2. Load Phase 2 Data
    store_info, service_times = load_extended_store_data() 
    _, stores, demands, _, time_matrix = load_data(file_name="PBAS - Data Case AH 2026.xlsx", day=weekday)
    demand = demands["demand"]

    # 3. RUN SECOND STAGE
    heuristic_time_stage(results, stores, store_info, service_times, time_matrix)

    # 4. Visualization Logic (Folium)
    depot_coords = (stores.loc[0, "Latitude"], stores.loc[0, "Longitude"])
    route_map = folium.Map(location=depot_coords, zoom_start=13, tiles="CartoDB positron")
    
    # Add Depot
    folium.Marker(depot_coords, tooltip="DC", icon=folium.Icon(color="red")).add_to(route_map)
    
    # Add Stores
    for i in range(1, len(stores)):
        lat, lon = stores.loc[i, "Latitude"], stores.loc[i, "Longitude"]
        folium.Marker([lat, lon], tooltip=f"Store: {stores.loc[i, 'Store nr']}", icon=folium.Icon(color="blue")).add_to(route_map)

    # Draw Routes
    truck_type_colours = {"Small": "#93C6E0", "Rigid": "#4A90D9", "City": "#1F5FA6", "Euro": "#0D2F6E", "EV_small": "#6DBF8A", "EV_big": "#1E7A3E"}
    for truck_id, (_, route, _, truck_type, _, _) in enumerate(results):
        route_coords = [depot_coords]
        colour = truck_type_colours.get(truck_type, "black")
        for node in route:
            route_coords.append((stores.loc[node, "Latitude"], stores.loc[node, "Longitude"]))
        route_coords.append(depot_coords)
        folium.PolyLine(route_coords, color=colour, weight=3, opacity=0.8).add_to(route_map)

    route_map.save(f"routes_{weekday}.html")

    df = pd.DataFrame(results, columns=["Weekday", "Route", "Quantities", "Truck type", "Distance (km)", "Duration (min)"])
    return df, total_cost, total_em


def full_week(lam):
    full_week_results = pd.DataFrame()
    total_cost, total_em = 0, 0
    with pd.ExcelWriter("schedule_final.xlsx") as writer:
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
            # Capture the 3 values: DataFrame, Cost, Emissions
            day_result, cost, em = run_and_visualize(weekday=day, cost_weight=lam, time_limit=3)
            if day_result is not None:
                day_result.to_excel(writer, sheet_name=day)
                full_week_results = pd.concat([full_week_results, day_result])
                total_cost += cost
                total_em += em
    return total_cost, total_em, full_week_results

if __name__ == "__main__":
    all_costs, all_ems = [], []
    all_lambdas = [0.4]
    for lam in all_lambdas:
        test_cost, test_em, _ = full_week(lam)
        all_costs.append(test_cost)
        all_ems.append(test_em)

    print(all_costs)
    print(all_ems)

    fig, ax1 = plt.subplots()

    # Plot temperature on the left y-axis
    ax1.plot(all_lambdas, all_costs, 'r-o', label='Transport cost (EUR)')
    ax1.set_xlabel('Lambda weight for cost efficiency')
    ax1.set_ylabel('Cost (EUR)', color='r')
    ax1.tick_params(axis='y', labelcolor='r')

    # Create a second y-axis for electricity consumption
    ax2 = ax1.twinx()
    ax2.plot(all_lambdas, all_ems, 'b-s', label='Emissions (kg CO2)')
    ax2.set_ylabel('Emissions (kg CO2)', color='b')
    ax2.tick_params(axis='y', labelcolor='b')

    # Add title and show plot
    plt.title('Trade-off between costs and emissions')
    fig.tight_layout()
    plt.show()

print()