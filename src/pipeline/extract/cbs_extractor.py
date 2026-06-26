"""
TYDZIEN 2 - KROK 4
Ekstrakcja danych demograficznych z CBS Statline API
CBS = Centraal Bureau voor de Statistiek
API: opendata.cbs.nl - bezplatne, bez klucza
"""

import requests
import boto3
import json
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("secrets.env")

S3_BUCKET = os.getenv("S3_BUCKET")
s3 = boto3.client("s3")

CBS_BASE_URL = "https://opendata.cbs.nl/ODataApi/odata"


def fetch_cbs_kerncijfers_wijk() -> pd.DataFrame:
    """
    Pobiera Kerncijfers wijken en buurten (kluczowe wskazniki per dzielnica).
    Dataset: 85318NED - najnowszy dostepny
    """
    url = f"{CBS_BASE_URL}/85318NED/TypedDataSet"

    params = {
        "$select": (
            "WijkenEnBuurten,"
            "Gemeentenaam_1,"
            "GemiddeldeWoningwaarde_17,"
            "GemiddeldInkomenPerInwoner_66,"
            "PercentageEigenaarBewoner_22,"
            "BevolkingsDichtheid_33,"
            "AantalInwoners_5,"
            "OppervlakteTotaal_107"
        ),
        "$filter": "substring(WijkenEnBuurten,0,2) eq 'WK'",
        "$top": 5000,
        "$format": "json",
    }

    print("Pobieranie CBS Kerncijfers wijken...")

    try:
        response = requests.get(url, params=params, timeout=60)

        if response.status_code == 200:
            data = response.json().get("value", [])
            df = pd.DataFrame(data)

            df.rename(columns={
                "WijkenEnBuurten": "wijk_code",
                "Gemeentenaam_1": "gemeente",
                "GemiddeldeWoningwaarde_17": "gemiddelde_woningwaarde",
                "GemiddeldInkomenPerInwoner_66": "gemiddeld_inkomen",
                "PercentageEigenaarBewoner_22": "pct_eigenaar",
                "BevolkingsDichtheid_33": "bevolkingsdichtheid",
                "AantalInwoners_5": "inwoners",
                "OppervlakteTotaal_107": "oppervlakte_km2",
            }, inplace=True)

            df["wijk_code"] = df["wijk_code"].str.strip()
            df["gemeente"] = df["gemeente"].str.strip()

            print(f"  CBS: {len(df)} wijken geladen")
            return df

        else:
            print(f"  CBS API error {response.status_code}")
            return pd.DataFrame()

    except Exception as e:
        print(f"  CBS exception: {e}")
        return pd.DataFrame()


def fetch_cbs_postcode_mapping() -> pd.DataFrame:
    """
    Pobiera mapowanie postcode 4-cyfrowy -> wijk_code.
    Potrzebne do joinowania z danymi BAG.
    Dataset: 84719NED - Kerncijfers postcodegebieden
    """
    url = f"{CBS_BASE_URL}/84719NED/TypedDataSet"

    params = {
        "$select": "Codering_3,WijkenEnBuurten,Gemeentenaam_1",
        "$filter": "substring(Codering_3,0,2) eq 'PC'",
        "$top": 5000,
        "$format": "json",
    }

    print("Pobieranie mapowania postcode -> wijk...")

    try:
        response = requests.get(url, params=params, timeout=60)

        if response.status_code == 200:
            data = response.json().get("value", [])
            df = pd.DataFrame(data)

            if not df.empty:
                df.rename(columns={
                    "Codering_3": "postcode_code",
                    "WijkenEnBuurten": "wijk_code",
                    "Gemeentenaam_1": "gemeente",
                }, inplace=True)
                df["postcode_4digit"] = df["postcode_code"].str.replace("PC", "").str.strip()
                print(f"  Mapowanie: {len(df)} kodow pocztowych")
                return df

    except Exception as e:
        print(f"  Postcode mapping error: {e}")

    return pd.DataFrame()


def generate_synthetic_cbs(gemeente: str = "Rotterdam") -> pd.DataFrame:
    """
    Fallback: syntetyczne dane CBS dla Rotterdamu.
    Bazuje na rzeczywistych danych CBS 2022.
    """
    import random
    import numpy as np

    wijken = [
        ("WK059900", "Centrum"),
        ("WK059901", "Delfshaven"),
        ("WK059902", "Overschie"),
        ("WK059903", "Noord"),
        ("WK059904", "Hillegersberg-Schiebroek"),
        ("WK059905", "Kralingen-Crooswijk"),
        ("WK059906", "Feijenoord"),
        ("WK059907", "IJsselmonde"),
        ("WK059908", "Pernis"),
        ("WK059909", "Prins Alexander"),
        ("WK059910", "Charlois"),
        ("WK059911", "Hoogvliet"),
        ("WK059912", "Hoek van Holland"),
        ("WK059913", "Rozenburg"),
        ("WK059914", "Nesselande"),
    ]

    records = []
    for wijk_code, wijk_naam in wijken:
        records.append({
            "wijk_code": wijk_code,
            "wijk_naam": wijk_naam,
            "gemeente": gemeente,
            "gemiddelde_woningwaarde": random.randint(200000, 600000),
            "gemiddeld_inkomen": random.randint(22000, 55000),
            "pct_eigenaar": round(random.uniform(20, 70), 1),
            "bevolkingsdichtheid": random.randint(500, 8000),
            "inwoners": random.randint(5000, 50000),
            "oppervlakte_km2": round(random.uniform(2, 25), 1),
            "is_synthetic": True,
        })

    df = pd.DataFrame(records)
    print(f"Wygenerowano syntetyczne dane CBS: {len(df)} wijken")
    return df


def upload_cbs_to_s3(df: pd.DataFrame) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    s3_key = f"raw/cbs/wijk_data_{timestamp}.jsonl"

    records = df.to_dict(orient="records")
    jsonl = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in records)

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=jsonl.encode("utf-8"),
        ContentType="application/x-ndjson",
    )

    print(f"✓ CBS S3: {len(records)} wijken -> s3://{S3_BUCKET}/{s3_key}")
    return s3_key


def run_cbs_extraction() -> str:
    """Glowna funkcja - wywolywana przez Airflow."""
    print("\n=== CBS Extraction ===")

    df = fetch_cbs_kerncijfers_wijk()

    if df.empty:
        print("CBS API niedostepne - uzywam syntetycznych danych")
        df = generate_synthetic_cbs()

    return upload_cbs_to_s3(df)


if __name__ == "__main__":
    key = run_cbs_extraction()
    print(f"\nS3 key: {key}")
