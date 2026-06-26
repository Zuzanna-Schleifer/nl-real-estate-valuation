"""
TYDZIEN 2 - KROK 2
Ekstrakcja wartosci WOZ (Waardering Onroerende Zaken)
WOZ = oficjalna wycena podatkowa nieruchomosci - proxy ceny rynkowej
Zrodlo: PDOK open data (nationaalgeoregister.nl) - bezplatne
"""

import requests
import boto3
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("secrets.env")

S3_BUCKET = os.getenv("S3_BUCKET")
s3 = boto3.client("s3")


def fetch_woz_pdok(gemeente_code: str, max_features: int = 5000) -> list:
    """
    Pobiera dane WOZ przez PDOK WFS API.
    PDOK = Publieke Dienstverlening Op de Kaart - rządowy serwis geodanych NL.
    """
    url = "https://service.pdok.nl/kadaster/kadastralekaart/wfs/v5_0"

    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "kadastralekaart:Perceel",
        "outputFormat": "application/json",
        "count": max_features,
        "srsName": "EPSG:4326",
    }

    print(f"Pobieranie danych z PDOK WFS...")

    try:
        response = requests.get(url, params=params, timeout=60)

        if response.status_code == 200:
            data = response.json()
            features = data.get("features", [])
            print(f"  Pobrano {len(features)} parcel z PDOK")
            return features
        else:
            print(f"  PDOK error {response.status_code}")
            return []

    except Exception as e:
        print(f"  Blad PDOK: {e}")
        return []


def fetch_woz_register(postcodes: list) -> list:
    """
    Alternatywne zrodlo: WOZ register API.
    Pobiera wartosci WOZ dla listy kodow pocztowych.
    """
    base_url = "https://api.wozregister.nl/wozobjecten"
    results = []

    for postcode in postcodes[:50]:  # limit dla testu
        try:
            response = requests.get(
                base_url,
                params={"postcode": postcode, "pageSize": 100},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                objects = data.get("_embedded", {}).get("wozobjecten", [])
                results.extend(objects)

        except Exception:
            continue

    print(f"WOZ Register: {len(results)} obiektow")
    return results


def generate_synthetic_woz(gemeente: str, n: int = 5000) -> list:
    """
    Fallback: generuje syntetyczne dane WOZ jesli API jest niedostepne.
    Uzywane do testow i developmentu.
    Rozklady cen bazuja na rzeczywistych danych z Funda.nl 2023.
    """
    import random
    import numpy as np

    price_profiles = {
        "rotterdam": {"mean": 320000, "std": 120000, "min": 80000, "max": 1500000},
        "amsterdam": {"mean": 550000, "std": 200000, "min": 150000, "max": 3000000},
        "den_haag": {"mean": 380000, "std": 140000, "min": 90000, "max": 1800000},
        "utrecht": {"mean": 420000, "std": 160000, "min": 100000, "max": 2000000},
    }

    profile = price_profiles.get(gemeente, price_profiles["rotterdam"])

    postcodes_rotterdam = [
        "3011", "3012", "3013", "3014", "3015", "3016",
        "3021", "3022", "3023", "3024", "3025",
        "3031", "3032", "3033", "3034", "3035",
        "3041", "3042", "3043", "3044", "3045",
        "3051", "3052", "3053", "3054", "3055",
    ]

    records = []
    for i in range(n):
        woz_raw = np.random.lognormal(
            mean=np.log(profile["mean"]),
            sigma=0.4
        )
        woz_waarde = max(profile["min"], min(profile["max"], int(woz_raw)))

        postcode_4 = random.choice(postcodes_rotterdam)
        letter_pairs = ["AA", "AB", "AC", "AD", "AE", "BA", "BB", "BC"]
        postcode = f"{postcode_4}{random.choice(letter_pairs)}"

        records.append({
            "woz_object_nummer": f"WOZ{gemeente.upper()[:3]}{i:06d}",
            "postcode": postcode,
            "huisnummer": random.randint(1, 200),
            "woz_waarde": woz_waarde,
            "peildatum": "2023-01-01",
            "gebruikscode": random.choices(
                ["1000", "2000", "3000"],
                weights=[0.75, 0.15, 0.10]
            )[0],
            "is_synthetic": True,
        })

    print(f"Wygenerowano {len(records)} syntetycznych rekordow WOZ dla {gemeente}")
    return records


def upload_woz_to_s3(data: list, gemeente: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    s3_key = f"raw/woz/gemeente={gemeente}/batch_{timestamp}.jsonl"

    jsonl = "\n".join(json.dumps(r, ensure_ascii=False) for r in data)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=jsonl.encode("utf-8"),
        ContentType="application/x-ndjson",
    )

    print(f"✓ WOZ S3: {len(data)} rekordow -> s3://{S3_BUCKET}/{s3_key}")
    return s3_key


def run_woz_extraction(gemeente_code: str, gemeente_naam: str) -> str:
    """Glowna funkcja - wywolywana przez Airflow."""
    print(f"\n=== WOZ Extraction: {gemeente_naam} ===")

    # Probuj prawdziwe API, fallback na syntetyczne
    data = fetch_woz_pdok(gemeente_code)

    if not data:
        print("PDOK niedostepne - uzywam syntetycznych danych")
        data = generate_synthetic_woz(gemeente_naam, n=5000)

    return upload_woz_to_s3(data, gemeente_naam)


if __name__ == "__main__":
    key = run_woz_extraction("0599", "rotterdam")
    print(f"\nS3 key: {key}")
