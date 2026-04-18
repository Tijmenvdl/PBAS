import datetime
import pandas as pd

def to_minutes(t):
    """Converts time objects to minutes from midnight for OR-Tools."""
    if pd.isna(t): 
        return 0
    if isinstance(t, str):
        h, m = map(int, t.split(':'))
        return h * 60 + m
    if isinstance(t, (datetime.time, datetime.datetime)):
        return t.hour * 60 + t.minute
    return 0

def load_data(file_name: str):
    # Standard fleet data
    trucks = {
        "Small": {"cap": 18, "cost_km": 0.35, "cost_hour": 35, "emission_km": 0.4, "is_ev": False},
        "Rigid": {"cap": 30, "cost_km": 0.4, "cost_hour": 40, "emission_km": 0.65, "is_ev": False},
        "City": {"cap": 45, "cost_km": 0.48, "cost_hour": 48, "emission_km": 0.8, "is_ev": False},
        "Euro": {"cap": 56, "cost_km": 0.6, "cost_hour": 60, "emission_km": 1.1, "is_ev": False},
        "EV_small": {"cap": 14, "cost_km": 0.4, "cost_hour": 40, "emission_km": 0.0, "is_ev": True},
        "EV_big": {"cap": 36, "cost_km": 0.55, "cost_hour": 55, "emission_km": 0.0, "is_ev": True}
    }

    dc = {"long": 5.115950, "lat": 51.578056, "dock_cap": 2, "loading_time": 0.5}

    df_stores = pd.read_excel(
        file_name,
        sheet_name="Store General",
        usecols=["Store", "Store nr", "Longitude", "Latitude", "Max. allowed truck type", 
                 "Open \n(mon - sat)", "Close\n(mon - sat)", "Distance to DC (km)", "Driving time to DC"]
    )
    
    #Create the columns the model is looking for
    df_stores['open_min'] = df_stores["Open \n(mon - sat)"].apply(to_minutes)
    df_stores['close_min'] = df_stores["Close\n(mon - sat)"].apply(to_minutes)

    df_demand = pd.read_excel(
        file_name,
        sheet_name="New volume per store per day",
        usecols=["Store", "Day of week", "Total demand for this day"]
    )

    df_distances = pd.read_excel(
        file_name,
        sheet_name="Distances",
        usecols=["Origin Store nr", "Destination Store nr", "Distance (km)", "Driving time"]
    )

    return trucks, dc, df_stores, df_demand, df_distances

def create_dist_matrix(dist_df: pd.DataFrame, dist_from_dc: pd.DataFrame):
    store_order = [9999] + [s for s in dist_df["Origin Store nr"].unique()]
    
    # Distance matrix as integers
    dist_matrix = dist_df.pivot(index="Origin Store nr", columns="Destination Store nr", values="Distance (km)").fillna(0)
    dc_dist = dist_from_dc.set_index("Store nr")["Distance to DC (km)"]
    dist_matrix[9999] = dc_dist
    dist_matrix.loc[9999] = dc_dist
    dist_matrix.loc[9999, 9999] = 0
    dist_matrix = dist_matrix.loc[store_order, store_order]

    # Time Matrix: Convert driving times to minutes that count from midnight 
    time_matrix = dist_df.pivot(index="Origin Store nr", columns="Destination Store nr", values="Driving time").fillna(0)
    dc_time = dist_from_dc.set_index("Store nr")["Driving time to DC"]
    time_matrix[9999] = dc_time
    time_matrix.loc[9999] = dc_time
    time_matrix = time_matrix.map(to_minutes) #applymap deprecated in current pandas versions
    time_matrix = time_matrix.loc[store_order, store_order]

    return dist_matrix.astype(int), time_matrix.astype(int)

def demand_decompose(demand_df: pd.DataFrame):
    days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    return tuple(demand_df[demand_df["Day of week"] == day] for day in days_of_week)