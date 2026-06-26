"""
TYDZIEN 2 - KROK 1
Ekstrakcja danych adresowych z BAG (Basisregistratie Adressen en Gebouwen)
Zrodlo: api.bag.kadaster.nl - publiczne, bezplatne
"""

import requests
import boto3
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("secrets.env")

S3_BUCKET = os.getenv("S3_BUCKET")
s3 = boto3.client("s3")

# Publiczny klucz testowy BAG API (dla produkcji zamow wlasny na kadaster.nl)
BAG_API_KEY = "l7xx1f2691f2520d487b902f4e0b2188930"
BAG_BASE_URL = "https://api.bag.kadaster.nl/lvbag/individuelebevragingen/v2"


def fetch_bag_addresses(gemeente_code: str, max_pages: int = 20) -> list:
    """
    Pobiera adresy z BAG API dla danej gminy.

    gemeente_code:
      '0599' = Rotterdam
      '0363' = Amsterdam
      '0518' = Den Haag
      '0344' = Utrecht
    """
    headers = {
        "X-Api-Key": BAG_API_KEY,
        "Accept": "application/hal+json",
        "Accept-Crs": "epsg:28992",
    }

    results = []
    page = 1

    while page <= max_pages:
        params = {
            "gemeenteIdentificatie": gemeente_code,
            "huidig": "true",
            "pageSize": 100,
            "page": page,
        }

        try:
            response = requests.get(
                f"{BAG_BASE_URL}/adressen",
                headers=headers,
                params=params,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                embedded = data.get("_embedded", {}).get("adressen", [])

                if not embedded:
                    print(f"  Brak danych na stronie {page} - koniec")
                    break

                results.extend(embedded)
                print(f"  Strona {page}: +{len(embedded)} rekordow (lacznie: {len(results)})")

                if "_links" not in data or "next" not in data["_links"]:
                    break

                page += 1
                time.sleep(0.2)  # rate limiting - szanuj API

            elif response.status_code == 429:
                print("  Rate limit - czekam 5s...")
                time.sleep(5)

            else:
                print(f"  Blad API {response.status_code}: {response.text[:200]}")
                break

        except requests.exceptions.Timeout:
            print(f"  Timeout na stronie {page}, pomijam")
            page += 1

    return results


def fetch_verblijfsobject_details(adres_id: str) -> dict:
    """
    Pobiera szczegoly obiektu mieszkalnego: metraz, rok budowy, status.
    """
    headers = {
        "X-Api-Key": BAG_API_KEY,
        "Accept": "application/hal+json",
    }

    try:
        response = requests.get(
            f"{BAG_BASE_URL}/verblijfsobjecten",
            headers=headers,
            params={"adresseerbaarObjectIdentificatie": adres_id},
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            objects = data.get("_embedded", {}).get("verblijfsobjecten", [])
            if objects:
                obj = objects[0]
                return {
                    "oppervlakte": obj.get("oppervlakte"),
                    "gebruiksdoelen": obj.get("gebruiksdoelen", []),
                    "status": obj.get("status", {}).get("omschrijving"),
                    "bouwjaar": obj.get("oorspronkelijkBouwjaar"),
                }
    except Exception:
        pass

    return {}


def enrich_addresses(adressen: list, sample_size: int = 1000) -> list:
    """
    Wzbogaca adresy o metraz i rok budowy.
    sample_size: ile rekordow wzbogacic (pierwsze N)
    """
    enriched = []
    sample = adressen[:sample_size]

    for i, adres in enumerate(sample):
        adres_id = adres.get("adresseerbaarObjectIdentificatie", "")
        if adres_id:
            details = fetch_verblijfsobject_details(adres_id)
            adres.update(details)

        enriched.append(adres)

        if (i + 1) % 100 == 0:
            print(f"  Wzbogacono {i+1}/{len(sample)}")
            time.sleep(0.1)

    return enriched


def upload_to_s3(data: list, gemeente: str, data_type: str = "bag") -> str:
    """
    Zapisuje dane jako JSON Lines do S3.
    Format kluczy: raw/bag/gemeente=rotterdam/batch_20240101_120000.jsonl
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    s3_key = f"raw/{data_type}/gemeente={gemeente}/batch_{timestamp}.jsonl"

    jsonl = "\n".join(json.dumps(record, ensure_ascii=False) for record in data)

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=jsonl.encode("utf-8"),
        ContentType="application/x-ndjson",
    )

    print(f"✓ S3: {len(data)} rekordow -> s3://{S3_BUCKET}/{s3_key}")
    return s3_key


def run_bag_extraction(gemeente_code: str, gemeente_naam: str) -> str:
    """
    Glowna funkcja - wywolywana przez Airflow PythonOperator.
    Zwraca S3 key (dla XCom).
    """
    print(f"\n=== BAG Extraction: {gemeente_naam} ({gemeente_code}) ===")

    adressen = fetch_bag_addresses(gemeente_code)

    if not adressen:
        print("BAG API niedostepne - generuje syntetyczne dane")
        adressen = generate_synthetic_bag(gemeente_naam, n=5000)

    enriched = enrich_addresses(adressen, sample_size=1000)
    s3_key = upload_to_s3(enriched, gemeente_naam, "bag")
    return s3_key


def generate_synthetic_bag(gemeente: str, n: int = 5000) -> list:
    """Syntetyczne dane BAG dla testow."""
    import random
    import numpy as np

    straten = ["Coolsingel", "Blaak", "Witte de Withstraat", "Meent",
               "Hoogstraat", "Botersloot", "Pannekoekstraat", "Oudehavenkade"]
    postcodes = ["3011AA", "3011AB", "3012BA", "3013CC", "3014DD",
                 "3021EE", "3022FF", "3031GG", "3041HH", "3051II"]
    gebruiksdoelen = [["woonfunctie"]] * 8 + [["kantoorfunctie"], ["winkelfunctie"]]

    records = []
    for i in range(n):
        records.append({
            "adresseerbaarObjectIdentificatie": f"BAG{gemeente.upper()[:3]}{i:08d}",
            "openbareruimtenaam": random.choice(straten),
            "huisnummer": random.randint(1, 200),
            "postcode": random.choice(postcodes),
            "woonplaatsnaam": gemeente.capitalize(),
            "gemeente": gemeente.capitalize(),
            "oppervlakte": random.randint(40, 250),
            "gebruiksdoelen": random.choice(gebruiksdoelen),
            "status": "Verblijfsobject in gebruik",
            "bouwjaar": random.randint(1920, 2020),
            "is_synthetic": True,
        })

    print(f"Wygenerowano {len(records)} syntetycznych rekordow BAG dla {gemeente}")
    return records

if __name__ == "__main__":
    # Test lokalny
    key = run_bag_extraction("0599", "rotterdam")
    print(f"\nS3 key: {key}")
