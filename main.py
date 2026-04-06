from data_prep import load_data, create_dist_matrix

def solve():
    trucks, dc, df_stores, df_demand, df_distances = load_data("PBAS - Data Case AH 2026.xlsx")
    dist_matrix, time_matrix = create_dist_matrix(df_distances, df_stores)

    return None

if __name__ == "__main__":
    solve()