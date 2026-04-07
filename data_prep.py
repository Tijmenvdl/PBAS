"""Python file includes functions that generates data for the rest of the project"""

# Imports
import datetime
import pandas as pd

def load_data(file_name: str):
    """
    Function loads data from {file_name} and outputs data required for model solution in Google OR Tools.
    File should point to Iris' Excel file with distance-time data loaded.
    
    """
    trucks = {
        "Small": {"cap": 18, "cost_km": 0.35, "cost_hour": 35, "emission_km": 0.4, "is_ev": False},
        "Rigid": {"cap": 30, "cost_km": 0.4, "cost_hour": 40, "emission_km": 0.65, "is_ev": False},
        "City": {"cap": 45, "cost_km": 0.48, "cost_hour": 48, "emission_km": 0.8, "is_ev": False},
        "Euro": {"cap": 54, "cost_km": 0.6, "cost_hour": 60, "emission_km": 1.1, "is_ev": False},
        "EV_small": {"cap": 15, "cost_km": 0.4, "cost_hour": 40, "emission_km": 0.0, "is_ev": True},
        "EV_big": {"cap": 30, "cost_km": 0.55, "cost_hour": 55, "emission_km": 0.0, "is_ev": True}
    }

    dc = {"long": 5.115950, "lat": 51.578056, "dock_cap": 2, "loading_time": 0.5}

    df_stores = pd.read_excel(
        file_name,
        sheet_name="Store General",
        usecols=["Store", 
                 "Store nr", 
                 "Longitude", 
                 "Latitude", 
                 "Max. allowed truck type", 
                 "Open \n(mon - sat)", 
                 "Close\n(mon - sat)", 
                 "Distance to DC (km)",
                 "Driving time to DC"]
    )
    
    df_stores.rename(columns={
        "Open \n(mon - sat)": "opening_time",
        "Close\n(mon - sat)": "closing_time"
    }, inplace=True)

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
    """
    Function creates distance matrix to be used in callback function later in solution process.
    """

    store_order = [9999] + [s for s in dist_df["Origin Store nr"].unique()]

    dist_matrix = dist_df.pivot( # Create 2D-array for distances between stores
        index="Origin Store nr",
        columns="Destination Store nr",
        values="Distance (km)"
    ).fillna(0).astype(int) # integer conversion required for GoogleORTools
    
    # zero_time = 
    # null_time = f"{zero_time.hour}:{zero_time.minute:02d}"

    time_matrix = dist_df.pivot( # Create 2D-array for times between stores
        index="Origin Store nr",
        columns="Destination Store nr",
        values="Driving time"
    )
    # .fillna(datetime.datetime.strptime("0:00", "%H:%M").time())

    dc_dist = dist_from_dc.set_index("Store nr")["Distance to DC (km)"] # Capture distance-from-DC
    dc_time = dist_from_dc.set_index("Store nr")["Driving time to DC"] # Capture time-from-DC
    # dc_time["Driving time to DC"] = dc_time["Driving time to DC"].apply(
    #     lambda t: f"{t.hour}:{t.minute:02d}"
    # )

    dist_matrix[9999] = dc_dist # Set store nr of DC to 9999, slap DC distance and times on both sides of the 2D-array
    dist_matrix.loc[9999] = dc_dist
    dist_matrix.loc[9999, 9999] = 0 # 0 on diagonal


    time_matrix[9999] = dc_time 
    time_matrix.loc[9999] = dc_time

    # re-order so depot is at position 0, required for data manager
    dist_matrix = dist_matrix.loc[store_order, store_order]
    time_matrix = time_matrix.loc[store_order, store_order]

    return dist_matrix.astype(int), time_matrix

def demand_decompose(demand_df: pd.DataFrame):
    """Splits demand dataframe into separate sets for days of the week"""
    days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    return tuple(demand_df[demand_df["Day of week"] == day] for day in days_of_week)