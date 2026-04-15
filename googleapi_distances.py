# Import packages
import pandas as pd
import googlemaps
import time

df = pd.read_excel("C:\\Users\\20213830\\OneDrive - Tilburg University\\BAOR1\\Sem2\\PBAS\\PBAS - Data Case AH 2026.xlsx")
print(df.head())


api_key = 'AIzaSyDbQbWcOMObg93aoevQV7yYO14Kr4YxoFs'
gmaps = googlemaps.Client(key=api_key)

file_name = "C:\\Users\\20213830\\OneDrive - Tilburg University\\BAOR1\\Sem2\\PBAS\\PBAS - Data Case AH 2026.xlsx"
inputtab_name = 'Store General'
outputtab_name = 'Distances'

df = pd.read_excel(file_name, sheet_name=inputtab_name)

results = []

for i, origin_row in df.iterrows():
    origin_store_id = origin_row['Store nr']
    origin_city = origin_row['City']
    origin_coordinates = (origin_row['Latitude'], origin_row['Longitude'])

    for j, dest_row in df.iterrows():
        dest_store_id = dest_row['Store nr']
        dest_city = dest_row['City']
        dest_coordinates = (dest_row['Latitude'], dest_row['Longitude'])

        if origin_store_id == dest_store_id:
            continue
        try:
            matrix = gmaps.distance_matrix(origins=[origin_coordinates], destinations=[dest_coordinates], mode='driving')
            element = matrix['rows'][0]['elements'][0]
            
            if element['status'] == 'OK':
                distance_m = element['distance']['value']
                time_sec = element['duration']['value']
                distance = round(distance_m / 1000, 0) # Change to km and round to 0 decimals

                # Convert time to hours:minutes format
                total_minutes = round(time_sec / 60)
                hours = total_minutes // 60
                minutes = total_minutes % 60
                duration = f"{hours}:{minutes:02d}"

            else: 
                distance = "Error: "
                duration = "Error"

        except Exception as e:
            print(f"Error processing {origin_store_id} to {dest_store_id}: {e}")
            distance = "Failed"
            duration = "Failed"

        results.append({
            'Origin Store nr': origin_store_id,
            'Origin City': origin_city,
            'Destination Store nr': dest_store_id,
            'Destination City': dest_city,
            'Distance (km)': distance, 
            'Driving time': duration
            })

        time.sleep(0.05)

# Saving results to new tab in same excel file
output_df = pd.DataFrame(results)
with pd.ExcelWriter(file_name, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
    output_df.to_excel(writer, sheet_name=outputtab_name, index=False)



