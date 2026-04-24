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
    return t

def load_data(file_name: str, day: str):
    # Standard fleet data
    df_trucks = pd.DataFrame({
        "Small": {"cap": 18, "cost_km": 0.35, "cost_hour": 35, "emission_km": 0.4, "is_ev": False},
        "Rigid": {"cap": 30, "cost_km": 0.4, "cost_hour": 40, "emission_km": 0.65, "is_ev": False},
        "City": {"cap": 45, "cost_km": 0.48, "cost_hour": 48, "emission_km": 0.8, "is_ev": False},
        "Euro": {"cap": 54, "cost_km": 0.6, "cost_hour": 60, "emission_km": 1.1, "is_ev": False},
        "EV_small": {"cap": 14, "cost_km": 0.4, "cost_hour": 40, "emission_km": 0.0, "is_ev": True},
        "EV_big": {"cap": 36, "cost_km": 0.55, "cost_hour": 55, "emission_km": 0.0, "is_ev": True}
    }).T

    dc = pd.DataFrame([{"Store":0, "Store nr": "DC", "Longitude": 5.115950, "Latitude": 51.578056}])

    df_stores = pd.read_excel(
        file_name,
        sheet_name="Store General",
        usecols=["Store", "Store nr", "Longitude", "Latitude", "Max. allowed truck type", 
                 "Open \n(mon - sat)", "Close\n(mon - sat)", "Distance to DC (km)", "Driving time to DC"]
    )
    
    #Create the columns the model is looking for
    df_stores['open_min'] = df_stores["Open \n(mon - sat)"].apply(to_minutes)
    df_stores['close_min'] = df_stores["Close\n(mon - sat)"].apply(to_minutes)
    df_stores["Driving time to DC"] = df_stores["Driving time to DC"].apply(to_minutes)

    df_stores = pd.concat([dc, df_stores], axis=0).set_index("Store") # Add DC as first fictional store to sheet

    df_demand = pd.read_excel(
        file_name,
        sheet_name="New volume per store per day",
        usecols=["Store", "Day of week", "Total demand for this day"]
    ).rename(columns={"Store": "Store nr", "Total demand for this day": "demand"})

    df_demand = df_demand.merge(
        df_stores.reset_index()[["Store", "Store nr"]],
        on="Store nr"
    ).set_index("Store")

    df_distances = pd.read_excel(
        file_name,
        sheet_name="Distances",
        usecols=["Origin Store nr", "Destination Store nr", "Distance (km)", "Driving time"]
    )

    df_distances = df_distances.merge(
        df_stores.reset_index()[["Store", "Store nr"]], left_on="Origin Store nr", right_on="Store nr"
    ).merge(
        df_stores.reset_index()[["Store", "Store nr"]], left_on="Destination Store nr", right_on="Store nr", suffixes=("_origin", "_destination")
    )

    store_order = [0] + [s for s in df_distances["Store_origin"].unique()]
    
    # Distance matrix as integers
    dist_matrix = df_distances.pivot(index="Store_origin", columns="Store_destination", values="Distance (km)")
    dist_matrix[0] = df_stores["Distance to DC (km)"]
    dist_matrix.loc[0] = df_stores["Distance to DC (km)"]
    dist_matrix.fillna(0, inplace=True)

    time_matrix = df_distances.pivot(index="Store_origin", columns="Store_destination", values="Driving time")
    time_matrix[0] = df_stores["Driving time to DC"]
    time_matrix.loc[0] = df_stores["Driving time to DC"]
    time_matrix = time_matrix.map(to_minutes).astype(int) + 30 # includes loading times

    return df_trucks, df_stores, df_demand[df_demand["Day of week"] == day], dist_matrix, time_matrix
