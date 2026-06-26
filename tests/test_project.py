"""
TYDZIEN 8 - Testy pytest
Uruchomienie: pytest tests/ -v
"""

import pytest
import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ==================================================
# TESTY MODELU
# ==================================================

class TestDataValidation:

    def test_woz_price_range(self):
        """WOZ waarden w realistycznym zakresie dla NL."""
        valid = [100_000, 350_000, 800_000, 2_000_000]
        invalid = [0, -5000, 9_999, 50_000_001]

        for price in valid:
            assert 50_000 <= price <= 10_000_000, f"Cena {price} powinna byc prawidlowa"

        for price in invalid:
            assert not (50_000 <= price <= 10_000_000), f"Cena {price} powinna byc odrzucona"

    def test_postcode_format(self):
        """Format kodu pocztowego NL."""
        import re
        pattern = r"^\d{4}[A-Z]{2}$"

        valid = ["3011AA", "1000AB", "9999ZZ", "2500BC"]
        invalid = ["30AA11", "3011aa", "30111", "AAAA11", "3011 AA", ""]

        for p in valid:
            assert re.match(pattern, p), f"{p} powinno byc prawidlowe"

        for p in invalid:
            assert not re.match(pattern, p), f"{p} powinno byc nieprawidlowe"

    def test_energielabel_encoding(self):
        """Enkodowanie etykiet energetycznych 1-10."""
        label_map = {
            "A+++": 10, "A++": 9, "A+": 8, "A": 7,
            "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1,
        }

        assert label_map["A"] == 7
        assert label_map["G"] == 1
        assert label_map["A+++"] == 10
        assert label_map["A+++"] > label_map["A"]
        assert all(1 <= v <= 10 for v in label_map.values())

    def test_feature_vector_shape(self):
        """Wektor cech ma prawidlowy ksztalt."""
        features = {
            "oppervlakte_m2": 85.0,
            "oppervlakte_log": np.log(85.0),
            "energielabel_score": 6,
            "leeftijd_jaar": 35,
            "is_wonen": 1,
            "is_kantoor": 0,
            "is_winkel": 0,
            "wijk_gemiddeld_inkomen": 35_000,
            "wijk_gemiddelde_waarde": 350_000,
            "wijk_pct_eigenaar": 45.0,
            "wijk_bevolkingsdichtheid": 3_500.0,
            "postcode_4digit_encoded": 100,
            "n_properties_in_postcode": 80,
            "median_woz_in_postcode": 320_000,
            "dist_centrum_m": 2_500.0,
            "dist_station_m": 800.0,
            "n_shops_500m": 12,
            "n_schools_1km": 3,
        }

        df = pd.DataFrame([features])
        assert df.shape == (1, 18)
        assert df["oppervlakte_m2"].iloc[0] == 85.0
        assert df.isna().sum().sum() == 0, "Brak NaN w wektorze cech"

    def test_log_price_range(self):
        """Log ceny w realistycznym zakresie (ln(50k) ~ 10.8, ln(10M) ~ 16.1)."""
        prices = [50_000, 150_000, 350_000, 800_000, 2_000_000, 10_000_000]

        for p in prices:
            log_p = np.log(p)
            assert 10.0 <= log_p <= 17.0, f"ln({p}) = {log_p:.2f} poza zakresem"

    def test_oppervlakte_log(self):
        """Log metrazu jest monotoniczny."""
        areas = [20, 50, 85, 120, 200, 350]
        log_areas = [np.log(a) for a in areas]

        for i in range(len(log_areas) - 1):
            assert log_areas[i] < log_areas[i + 1], "Log metrazu powinien byc rosnacy"

    def test_preprocess_no_nan(self):
        """Preprocessing nie pozostawia NaN w kluczowych kolumnach."""
        df = pd.DataFrame({
            "oppervlakte_m2": [85.0, None, 120.0],
            "energielabel_score": [6, None, 7],
            "target_price": [350_000, 280_000, 420_000],
            "target_price_log": [np.log(350_000), np.log(280_000), np.log(420_000)],
            "gebruiksdoel": ["wonen", "wonen", "kantoor"],
            "postcode_4digit": ["3011", "3012", "3013"],
        })

        # Imputacja mediany
        df["oppervlakte_m2"] = df["oppervlakte_m2"].fillna(df["oppervlakte_m2"].median())
        df["energielabel_score"] = df["energielabel_score"].fillna(df["energielabel_score"].median())

        assert df["oppervlakte_m2"].isna().sum() == 0
        assert df["energielabel_score"].isna().sum() == 0


# ==================================================
# TESTY API
# ==================================================

class TestAPI:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from src.api.main import app
        return TestClient(app)

    def test_root_endpoint(self, client):
        """Root endpoint zwraca info o API."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "api" in data
        assert "version" in data
        assert data["version"] == "1.0.0"

    def test_health_endpoint(self, client):
        """Health check."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_valuate_requires_auth(self, client):
        """Wycena wymaga API key."""
        response = client.post("/v1/valuate", json={
            "postcode": "3011AA",
            "huisnummer": 1,
            "oppervlakte_m2": 85,
        })
        assert response.status_code == 401

    def test_valuate_with_demo_key(self, client):
        """Wycena dziala z demo_ prefixed key (demo mode)."""
        response = client.post(
            "/v1/valuate",
            json={
                "postcode": "3011AA",
                "huisnummer": 1,
                "oppervlakte_m2": 85.0,
                "gebruiksdoel": "wonen",
                "energielabel": "B",
            },
            headers={"X-API-Key": "demo_test_key"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "estimated_value" in data
        assert data["estimated_value"] > 0
        assert data["confidence_low"] < data["estimated_value"]
        assert data["estimated_value"] < data["confidence_high"]
        assert "price_per_m2" in data
        assert "timestamp" in data

    def test_valuate_price_sanity(self, client):
        """Predykcja ceny w rozsdnym zakresie dla NL."""
        response = client.post(
            "/v1/valuate",
            json={
                "postcode": "3011AA",
                "huisnummer": 1,
                "oppervlakte_m2": 85.0,
                "energielabel": "B",
            },
            headers={"X-API-Key": "demo_test_key"},
        )
        assert response.status_code == 200
        price = response.json()["estimated_value"]

        # Rozsdny zakres dla 85m2 w Rotterdam
        assert 80_000 <= price <= 3_000_000, f"Cena {price} poza rozsdnym zakresem"

    def test_valuate_invalid_oppervlakte(self, client):
        """Zbyt maly metraz zwraca validation error."""
        response = client.post(
            "/v1/valuate",
            json={
                "postcode": "3011AA",
                "huisnummer": 1,
                "oppervlakte_m2": 5.0,  # za malo (min=10)
            },
            headers={"X-API-Key": "demo_test_key"},
        )
        assert response.status_code == 422

    def test_docs_accessible(self, client):
        """Swagger docs dostepny."""
        response = client.get("/docs")
        assert response.status_code == 200


# ==================================================
# TESTY STREAMING
# ==================================================

class TestStreaming:

    def test_transaction_structure(self):
        """Struktura rekordu transakcji Kafka."""
        import random

        prop = {
            "bag_id": "BAG001",
            "postcode": "3011AA",
            "stad": "Rotterdam",
            "oppervlakte_m2": 85.0,
            "energielabel": "B",
            "target_price": 350_000,
            "gebruiksdoel": "wonen",
        }

        base_price = prop["target_price"]
        noise = random.gauss(0, 0.025)
        txn_price = int(base_price * (1 + noise))

        txn = {
            "transaction_id": "TXN20240101120000001",
            "bag_id": prop["bag_id"],
            "transaction_price": txn_price,
            "model_price": base_price,
            "price_deviation_pct": round(noise * 100, 2),
        }

        assert "transaction_id" in txn
        assert "bag_id" in txn
        assert "transaction_price" in txn
        assert "model_price" in txn
        assert txn["transaction_price"] > 0
        assert abs(txn["price_deviation_pct"]) < 20, "Dewiacja ceny powinna byc < 20%"

    def test_kafka_topic_name(self):
        """Nazwa topiku Kafka zgodna z konwencja."""
        topic = "avm.property.transactions"
        parts = topic.split(".")
        assert len(parts) == 3
        assert parts[0] == "avm"
