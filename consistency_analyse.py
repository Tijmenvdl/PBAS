import numpy as np
import pandas as pd
from main import run_and_visualize 

def run_monte_carlo(days, iterations=100):
    """
    Voert een Monte Carlo simulatie uit over meerdere dagen om de 
    robuustheid van de ritten te testen tegen onzekere reistijden.
    """
    all_stats = []

    for day in days:
        print(f"\n--- Start Simulatie voor {day} ---")
        
        # 1. Haal resultaten op uit jouw model
        # Let op: run_and_visualize geeft nu (df, total_cost, total_em) terug volgens de main file,
        # maar voor de simulatie hebben we de ruwe 'results' en 'time_matrix' nodig.
        # Zorg dat run_and_visualize in main.py deze waarden aan het einde teruggeeft!
        output = run_and_visualize(weekday=day, cost_weight=0.4, time_limit=60)
        
        if output is None or output[0] is None:
            continue
            
        # We halen de variabelen op die we aan de 'return' van run_and_visualize in main.py hebben toegevoegd
        results, stores, store_info, service_times, time_matrix = output

        # Converteer de DataFrame resultaten naar een lijst van tuples als dat nog niet zo is
        # (Afhankelijk van of je de 'results' lijst of de 'df' teruggeeft in main.py)
        raw_results = results.values.tolist() if isinstance(results, pd.DataFrame) else results

        for i in range(iterations):
            # STAP 2: Genereer nieuwe onzekere tijden (10% vertraging, 20% variatie)
            sim_time_matrix = time_matrix.copy()
            bias = 1.1 
            std_dev = 0.20
            
            # Voeg ruis toe
            noise = np.random.normal(bias, std_dev, size=sim_time_matrix.shape)
            sim_time_matrix = (sim_time_matrix * noise).clip(lower=1).astype(int)

            # STAP 3: Test de ritten tegen de nieuwe tijden
            violations = check_consistency(raw_results, stores, store_info, service_times, sim_time_matrix)
            
            all_stats.append({
                "day": day,
                "iteration": i,
                "violations": violations
            })

    return pd.DataFrame(all_stats)

def check_consistency(results, stores, store_info, service_times, sim_time_matrix):
    """
    Telt het aantal overschrijdingen van de sluitingstijd.
    """
    total_violations = 0
    
    for truck_id, route_data in enumerate(results):
        # UNPACKING FIX: Omdat je GitHub resultaten 6 kolommen hebben: 
        # (Weekday, Route, Quantities, Truck type, Distance, Duration)
        # We moeten de juiste indexen pakken:
        weekday = route_data[0]
        route = route_data[1]
        truck_type = route_data[3]

        current_time = 480  # 08:00
        previous_node = 0
        
        for store in route:
            # Reistijd met ruis uit de sim_time_matrix
            travel_time = sim_time_matrix.at[previous_node, store]
            current_time += travel_time
            
            # Zoek winkel info op via Store nr
            store_nr = stores.loc[store, "Store nr"]
            open_time = store_info[store_nr]['open']
            close_time = store_info[store_nr]['close']
            
            # Wachten bij vroege aankomst
            if current_time < open_time:
                current_time = open_time
            
            # Check of we te laat zijn
            if current_time > close_time:
                total_violations += 1

            # Service tijd (unloading)
            current_time += service_times.get(truck_type, 30)
            previous_node = store
            
    return total_violations

if __name__ == "__main__":
    days_to_test = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    
    # Run de simulatie
    df_results = run_monte_carlo(days_to_test, iterations=50)
    
    if not df_results.empty:
        # Analyseer resultaten
        summary = df_results.groupby("day")["violations"].agg(["mean", "max", "std"])
        print("\n--- Simulatie Resultaten (Aantal te late winkels) ---")
        print(summary)
        
        # Opslaan
        df_results.to_excel("monte_carlo_results_final.xlsx")