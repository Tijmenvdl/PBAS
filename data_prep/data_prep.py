import pandas as pd
import datetime

def to_minutes(t):
    """
    Standardized utility to convert various time formats to minutes from midnight.
    Handles: datetime objects, strings ('HH:MM'), and NaNs.
    """
    if pd.isna(t) or t == "": 
        return 0
    if isinstance(t, (datetime.time, datetime.datetime)):
        return t.hour * 60 + t.minute
    if isinstance(t, str):
        try:
            parts = t.split(':')
            # Works for both HH:MM and HH:MM:SS
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            return 0
    return t

def load_data(file_name: str, day: str):
    """
    Phase 1 Loader: Returns fleet data, stores, demand for a specific day, 
    and the distance/time matrices.
    """
    # 1. Standard fleet data (Hardcoded costs/emissions)
    df_trucks_config = pd.DataFrame({
        "Small": {"cap": 18, "cost_km": 0.35, "cost_hour": 35, "emission_km": 0.4, "is_ev": False},
        "Rigid": {"cap": 30, "cost_km": 0.4, "cost_hour": 40, "emission_km": 0.65, "is_ev": False},
        "City": {"cap": 45, "cost_km": 0.48, "cost_hour": 48, "emission_km": 0.8, "is_ev": False},
        "Euro": {"cap": 54, "cost_km": 0.6, "cost_hour": 60, "emission_km": 1.1, "is_ev": False},
        "EV_small": {"cap": 14, "cost_km": 0.4, "cost_hour": 40, "emission_km": 0.0, "is_ev": True},
        "EV_big": {"cap": 36, "cost_km": 0.55, "cost_hour": 55, "emission_km": 0.0, "is_ev": True}
    }).T

    # 2. Store General Data
    dc = pd.DataFrame([{"Store": 0, "Store nr": "DC", "Longitude": 5.115950, "Latitude": 51.578056}])
    
    df_stores = pd.read_excel(
        file_name,
        sheet_name="Store General",
        usecols=["Store", "Store nr", "Longitude", "Latitude", "Max. allowed truck type", 
                 "Open \n(mon - sat)", "Close\n(mon - sat)", "Distance to DC (km)", "Driving time to DC"]
    )
    
    df_stores['open_min'] = df_stores["Open \n(mon - sat)"].apply(to_minutes)
    df_stores['close_min'] = df_stores["Close\n(mon - sat)"].apply(to_minutes)
    df_stores["Driving time to DC"] = df_stores["Driving time to DC"].apply(to_minutes)
    df_stores = pd.concat([dc, df_stores], axis=0).set_index("Store")

    # 3. Demand Data
    df_demand = pd.read_excel(
        file_name,
        sheet_name="New volume per store per day",
        usecols=["Store", "Day of week", "Total demand for this day"]
    ).rename(columns={"Store": "Store nr", "Total demand for this day": "demand"})

    df_demand = df_demand.merge(
        df_stores.reset_index()[["Store", "Store nr"]], on="Store nr"
    ).set_index("Store")
 
    # 4. Distances and Time Matrices
    df_distances = pd.read_excel(
        file_name, sheet_name="Distances",
        usecols=["Origin Store nr", "Destination Store nr", "Distance (km)", "Driving time"]
    )

    df_distances = df_distances.merge(
        df_stores.reset_index()[["Store", "Store nr"]], left_on="Origin Store nr", right_on="Store nr"
    ).merge(
        df_stores.reset_index()[["Store", "Store nr"]], left_on="Destination Store nr", right_on="Store nr", suffixes=("_origin", "_destination")
    )

    # Pivot Distance Matrix
    dist_matrix = df_distances.pivot(index="Store_origin", columns="Store_destination", values="Distance (km)")
    dist_matrix[0] = df_stores["Distance to DC (km)"]
    dist_matrix.loc[0] = df_stores["Distance to DC (km)"]
    dist_matrix.fillna(0, inplace=True)

    # Pivot Time Matrix
    time_matrix = df_distances.pivot(index="Store_origin", columns="Store_destination", values="Driving time")
    time_matrix[0] = df_stores["Driving time to DC"]
    time_matrix.loc[0] = df_stores["Driving time to DC"]
    # +30 minutes for loading at DC/Store
    time_matrix = time_matrix.map(to_minutes).astype(int) + 30 

    return df_trucks_config, df_stores, df_demand[df_demand["Day of week"] == day], dist_matrix, time_matrix

def load_extended_store_data(file_name: str = "PBAS - Data Case AH 2026.xlsx"):
    """
    Phase 2 Loader: Returns detailed store opening/closing dictionary 
    and truck-specific service (unloading) times.
    """
    df_stores = pd.read_excel(file_name, sheet_name="Store General")
    store_info = {}
    
    for _, row in df_stores.iterrows():
        s_nr = row['Store nr']
        # Handle potential variations in Excel column naming (with/without newlines)
        open_col = 'Open \n(mon - sat)' if 'Open \n(mon - sat)' in row else 'Open (mon - sat)'
        close_col = 'Close\n(mon - sat)' if 'Close\n(mon - sat)' in row else 'Close (mon - sat)'
        
        store_info[s_nr] = {
            'open': to_minutes(row.get(open_col, "08:00")),
            'close': to_minutes(row.get(close_col, "22:00")),
            'dist_to_dc': row.get('Distance to DC (km)', 0)
        }
    
    # Load unloading times from "Truck types" sheet
    df_truck_types = pd.read_excel(file_name, sheet_name="Truck types", skiprows=1)
    service_times = {}
    
    for _, row in df_truck_types.iterrows():
        ttype = row['Trucktype']
        if pd.isna(ttype): 
            continue
        
        # Extract digits from string like "30 min" or "45 minutes"
        raw_time = str(row.get('Unloading time at store (by driver)', "30")) 
        time_val = int(''.join(filter(str.isdigit, raw_time))) if any(c.isdigit() for c in raw_time) else 30
        service_times[ttype] = time_val

    return store_info, service_times

# --- Test Script ---
if __name__ == "__main__":
    FILE = "PBAS - Data Case AH 2026.xlsx"
    print("Testing Merged Data Prep...")
    
    # Test Phase 1
    trucks, stores, demand, dists, times = load_data(FILE, "Sat")
    print(f"Phase 1 Loaded: {len(stores)} stores found.")
    
    # Test Phase 2
    s_info, s_times = load_extended_store_data(FILE)
    print(f"Phase 2 Loaded: Service time for 'Euro' is {s_times.get('Euro')} min.")