"""
TYDZIEN 4 - KROK 1
PySpark job: obliczanie spatial features (odleglosci, POI)
dla kazdej nieruchomosci w mart_features.

Spatial features to 30-40% predykcyjnej sily modelu AVM.
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, IntegerType, StructType, StructField
import geopandas as gpd
import osmnx as ox
import pandas as pd
import numpy as np
import snowflake.connector
import os
from shapely.geometry import Point
from dotenv import load_dotenv

load_dotenv("secrets.env")


def create_spark_session() -> SparkSession:
    return (
        SparkSession.builder.appName("AVM_SpatialFeatures")
        .config("spark.driver.memory", "4g")
        .config("spark.executor.memory", "4g")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .getOrCreate()
    )


def download_osm_pois(city: str = "Rotterdam, Netherlands") -> dict:
    """
    Pobiera punkty zainteresowania z OpenStreetMap.
    Uzywa biblioteki osmnx (bezplatne dane OSM).
    """
    print(f"Pobieranie OSM POI dla {city}...")

    pois = {}

    poi_configs = {
        "stations": {"railway": ["station", "halt"]},
        "metro": {"railway": "subway_entrance"},
        "shops": {"shop": True},
        "supermarkets": {"shop": "supermarket"},
        "schools": {"amenity": ["school", "kindergarten"]},
        "universities": {"amenity": "university"},
        "hospitals": {"amenity": "hospital"},
        "parks": {"leisure": "park"},
        "water": {"natural": "water"},
    }

    for poi_type, tags in poi_configs.items():
        try:
            gdf = ox.features_from_place(city, tags=tags)
            gdf_points = gdf.copy()
            gdf_points["geometry"] = gdf_points.geometry.centroid
            pois[poi_type] = gdf_points[["geometry"]].copy()
            print(f"  {poi_type}: {len(gdf_points)} obiektow")
        except Exception as e:
            print(f"  {poi_type}: blad ({e}) - pomijam")
            pois[poi_type] = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    # Centrum miasta (stale wspolrzedne)
    city_centers = {
        "rotterdam": (51.9244, 4.4777),
        "amsterdam": (52.3676, 4.9041),
        "den_haag": (52.0705, 4.3007),
        "utrecht": (52.0907, 5.1214),
    }
    center_city = city.split(",")[0].lower().strip()
    lat, lon = city_centers.get(center_city, (51.9244, 4.4777))

    pois["centrum"] = gpd.GeoDataFrame(
        geometry=[Point(lon, lat)], crs="EPSG:4326"
    )
    print(f"  centrum: ({lat}, {lon})")

    return pois


def calc_nearest_distance(lat: float, lon: float, pois_gdf: gpd.GeoDataFrame) -> float:
    """Odleglosc do najblizszego POI w metrach (EPSG:28992 = RD New, metryczna)."""
    if pois_gdf is None or len(pois_gdf) == 0:
        return None

    try:
        point = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326")
        point_m = point.to_crs("EPSG:28992")
        pois_m = pois_gdf.to_crs("EPSG:28992")
        distances = pois_m.geometry.distance(point_m.geometry.iloc[0])
        return float(distances.min())
    except Exception:
        return None


def count_pois_in_radius(
    lat: float, lon: float, pois_gdf: gpd.GeoDataFrame, radius_m: float
) -> int:
    """Liczba POI w promieniu radius_m metrow."""
    if pois_gdf is None or len(pois_gdf) == 0:
        return 0

    try:
        point = gpd.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326")
        point_m = point.to_crs("EPSG:28992")
        pois_m = pois_gdf.to_crs("EPSG:28992")
        distances = pois_m.geometry.distance(point_m.geometry.iloc[0])
        return int((distances <= radius_m).sum())
    except Exception:
        return 0


def generate_mock_coordinates(postcode: str) -> tuple:
    """
    Proxy: generuje wspolrzedne na podstawie kodu pocztowego.
    W produkcji uzyj: BAG geometria lub geocoding API.
    Centrum Rotterdam: 51.9244, 4.4777
    """
    if not postcode or len(postcode) < 4:
        return (51.9244, 4.4777)

    try:
        # Deterministyczne przesunicie na podstawie 4-cyfrowego kodu
        prefix = int(postcode[:4])

        # Rotterdam: kody 3000-3099
        # Odwzorowanie na siatke geograficzna
        base_lat = 51.85 + (prefix - 3000) * 0.001
        base_lon = 4.35 + (prefix - 3000) * 0.0015

        # Male losowe przesunicie (symulacja roznych adresow w tym samym kodzie)
        import hashlib
        h = int(hashlib.md5(postcode.encode()).hexdigest()[:4], 16)
        noise_lat = (h % 100 - 50) * 0.0001
        noise_lon = (h % 100 - 50) * 0.0002

        lat = min(max(base_lat + noise_lat, 51.85), 52.00)
        lon = min(max(base_lon + noise_lon, 4.30), 4.65)

        return (lat, lon)
    except Exception:
        return (51.9244, 4.4777)


def compute_spatial_batch(df_batch: pd.DataFrame, pois: dict) -> pd.DataFrame:
    """Oblicza spatial features dla jednej partycji DataFrame."""
    results = []

    for _, row in df_batch.iterrows():
        postcode = row.get("postcode", "")
        lat, lon = generate_mock_coordinates(postcode)

        spatial = {
            "bag_id": row["bag_id"],
            "lat": lat,
            "lon": lon,
            "dist_centrum_m": calc_nearest_distance(lat, lon, pois.get("centrum")),
            "dist_station_m": calc_nearest_distance(lat, lon, pois.get("stations")),
            "dist_metro_m": calc_nearest_distance(lat, lon, pois.get("metro")),
            "dist_water_m": calc_nearest_distance(lat, lon, pois.get("water")),
            "dist_hospital_m": calc_nearest_distance(lat, lon, pois.get("hospitals")),
            "n_shops_500m": count_pois_in_radius(lat, lon, pois.get("shops"), 500),
            "n_supermarkets_1km": count_pois_in_radius(lat, lon, pois.get("supermarkets"), 1000),
            "n_schools_1km": count_pois_in_radius(lat, lon, pois.get("schools"), 1000),
            "n_parks_1km": count_pois_in_radius(lat, lon, pois.get("parks"), 1000),
        }
        results.append(spatial)

    return pd.DataFrame(results)


def update_snowflake_spatial(df_spatial: pd.DataFrame):
    """Aktualizuje kolumny spatial w mart_features Snowflake."""
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database="AVM_DB",
        warehouse="AVM_WH",
        schema="MART",
    )

    cursor = conn.cursor()

    # Dodaj kolumny jesli nie istnieja
    new_cols = [
        ("lat", "FLOAT"),
        ("lon", "FLOAT"),
        ("dist_centrum_m", "FLOAT"),
        ("dist_station_m", "FLOAT"),
        ("dist_metro_m", "FLOAT"),
        ("dist_water_m", "FLOAT"),
        ("dist_hospital_m", "FLOAT"),
        ("n_shops_500m", "INTEGER"),
        ("n_supermarkets_1km", "INTEGER"),
        ("n_schools_1km", "INTEGER"),
        ("n_parks_1km", "INTEGER"),
    ]

    for col_name, col_type in new_cols:
        try:
            cursor.execute(
                f"ALTER TABLE AVM_DB.MART.MART_FEATURES ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
            )
        except Exception:
            pass

    # Batch update
    print(f"Aktualizuje {len(df_spatial)} rekordow...")
    batch_size = 500

    for i in range(0, len(df_spatial), batch_size):
        batch = df_spatial.iloc[i : i + batch_size]

        for _, row in batch.iterrows():
            cursor.execute("""
                UPDATE AVM_DB.MART.MART_FEATURES
                SET
                    lat = %s,
                    lon = %s,
                    dist_centrum_m = %s,
                    dist_station_m = %s,
                    dist_metro_m = %s,
                    dist_water_m = %s,
                    dist_hospital_m = %s,
                    n_shops_500m = %s,
                    n_supermarkets_1km = %s,
                    n_schools_1km = %s,
                    n_parks_1km = %s
                WHERE bag_id = %s
            """, (
                row.get("lat"),
                row.get("lon"),
                row.get("dist_centrum_m"),
                row.get("dist_station_m"),
                row.get("dist_metro_m"),
                row.get("dist_water_m"),
                row.get("dist_hospital_m"),
                row.get("n_shops_500m"),
                row.get("n_supermarkets_1km"),
                row.get("n_schools_1km"),
                row.get("n_parks_1km"),
                row["bag_id"],
            ))

        conn.commit()
        print(f"  Zaktualizowano {min(i + batch_size, len(df_spatial))}/{len(df_spatial)}")

    conn.close()
    print("✓ Spatial features zaktualizowane w Snowflake")


def run_spatial_features_job(city: str = "Rotterdam, Netherlands", limit: int = 10000):
    """Glowna funkcja - uruchamiana przez Airflow lub recznie."""
    print("\n=== PySpark Spatial Features Job ===")

    spark = create_spark_session()
    spark.sparkContext.setLogLevel("WARN")

    # 1. Pobierz dane z Snowflake
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database="AVM_DB",
        warehouse="AVM_WH",
        schema="MART",
    )

    df_pd = pd.read_sql(
        f"SELECT bag_id, postcode, stad FROM MART_FEATURES LIMIT {limit}",
        conn
    )
    conn.close()

    print(f"Zaladowano {len(df_pd)} rekordow")

    # 2. Konwertuj na Spark
    df_spark = spark.createDataFrame(df_pd)
    print(f"Spark DataFrame: {df_spark.count()} rekordow, {len(df_spark.columns)} kolumn")

    # 3. Pobierz POI z OSM
    pois = download_osm_pois(city)

    # 4. Oblicz spatial features przez pandas (na driverze, dla <10k rekordow)
    print("Obliczam spatial features...")
    df_spatial = compute_spatial_batch(df_pd, pois)
    print(f"Obliczono features dla {len(df_spatial)} rekordow")

    # 5. Aktualizuj Snowflake
    update_snowflake_spatial(df_spatial)

    spark.stop()
    print("\n✓ PySpark Spatial job zakończony")


if __name__ == "__main__":
    run_spatial_features_job(limit=1000)  # limit=1000 dla pierwszego testu
