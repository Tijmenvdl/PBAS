import folium

from data_prep import load_data
from basic_vrp import basic_vrp_framework

def show_solution():
    """Uses Folium to create map visual with solution"""
    data, routing, manager, solution = basic_vrp_framework()

    _, dc, df_stores, _, _ = load_data("PBAS - Data Case AH 2026.xlsx")

    depot_coords = (dc["lat"], dc["long"])
    coord_lookup = df_stores.set_index("Store nr")[["Latitude", "Longitude"]].to_dict("index")

    m = folium.Map(location=depot_coords, zoom_start=10)
    colours = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue"]

    for vehicle_id in range(data["n_vehicles"]):
        index = routing.Start(vehicle_id)
        route_coords = [depot_coords] # start at depot

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            store_nr = data["node_index_to_store"][node]

            if store_nr != 9999:
                lat = coord_lookup[store_nr]["Latitude"]
                lon = coord_lookup[store_nr]["Longitude"]
                route_coords.append((lat, lon))
                folium.Marker([lat, lon],
                              tooltip=store_nr,
                              icon=folium.Icon(
                                  color=colours[vehicle_id % len(colours)]
                              )).add_to(m)
                
            index = solution.Value(routing.NextVar(index))

        route_coords.append(depot_coords) # close route at DC

        if len(route_coords) > 2: # Add only used vehicles
            folium.PolyLine(route_coords, color=colours[vehicle_id % len(colours)],  weight=2).add_to(m)

    folium.Marker(depot_coords, tooltip="DC", icon=folium.Icon(color="black", icon="home")).add_to(m)       

    m.save("routes.html")

if __name__ == "__main__":
    show_solution() # test

print()