# Dutch AVM — Automated Valuation Model

> Real estate valuation API for the Dutch market | XGBoost · Snowflake · Kafka · PySpark · FastAPI

[![CI/CD](https://github.com/Zuzanna-Schleifer/dutch-avm/actions/workflows/ci.yml/badge.svg)](https://github.com/Zuzanna-Schleifer/dutch-avm/actions)

## Architektura

```
Data Sources          Pipeline              ML Core           Product
─────────────         ─────────────         ─────────────     ─────────────
BAG (Kadaster) ──┐    AWS S3               XGBoost           FastAPI REST
WOZ Register  ──┼──> (raw lake)  ──> dbt ──> + Optuna ──>   + Stripe
EP-online     ──┤    Snowflake   Airflow   + SHAP            + Rate limit
CBS Statline  ──┘    (warehouse) DAG       + MLflow     ──>  React dashboard
OpenStreetMap ───── PySpark                               ──> Vercel + Railway
Kafka stream  ─────────────────────────────────────────> Snowflake stream
```

## Stack

| Kategoria      | Technologie                              |
|----------------|------------------------------------------|
| **Languages**  | Python 3.11, SQL, TypeScript             |
| **Warehousing**| Snowflake, dbt (ELT), AWS S3             |
| **Orchestration** | Apache Airflow 2.8                    |
| **Big Data**   | PySpark 3.5, GeoPandas, OSMnx            |
| **Streaming**  | Apache Kafka (Confluent)                 |
| **ML**         | XGBoost, Optuna HPO, SHAP, MLflow        |
| **Quality**    | Great Expectations, dbt tests            |
| **API**        | FastAPI, Pydantic, Stripe, Redis         |
| **Deploy**     | Docker, GitHub Actions, Railway, Vercel  |
| **Frontend**   | React, TypeScript, Recharts, Leaflet     |

## Quick Start

### 1. Wymagania
- Docker Desktop
- Python 3.11+
- Node.js 20+
- Konto Snowflake (free trial)
- Konto AWS (free tier)

### 2. Setup

```bash
# Klonuj repo
git clone https://github.com/Zuzanna-Schleifer/dutch-avm.git
cd dutch-avm

# Uzupelnij credentials
cp secrets.env.example secrets.env
# edytuj secrets.env: wklej Snowflake account, AWS keys, EP-online key

# Uruchom Snowflake setup (w Snowsight web UI)
# Wykonaj: docs/snowflake_setup.sql

# Uruchom serwisy
docker compose up airflow-init  # tylko raz
docker compose up -d

# Zainstaluj Python dependencies
pip install -r requirements.txt
```

### 3. Uruchom pipeline

```bash
# Snowflake: initial setup (tabele + S3 stage)
python src/pipeline/load/snowflake_loader.py

# Uruchom DAG recznie (lub przez Airflow UI: localhost:8080)
python src/pipeline/extract/bag_extractor.py
python src/pipeline/extract/woz_extractor.py
python src/pipeline/extract/cbs_extractor.py
python src/pipeline/extract/ep_online_extractor.py

# dbt transformacje
cd dbt/avm_dbt
dbt run --profiles-dir .
dbt test --profiles-dir .
```

### 4. Spatial features (PySpark)

```bash
python src/pipeline/transform/spatial_features.py
```

### 5. Kafka streaming

```bash
# Terminal 1
python src/streaming/kafka_price_producer.py

# Terminal 2
python src/streaming/kafka_consumer.py
```

### 6. Trening modelu

```bash
python src/models/train.py
# Po treningu: skopiuj Run ID do secrets.env -> MLFLOW_MODEL_RUN_ID
```

### 7. API

```bash
uvicorn src.api.main:app --reload --port 8000
# Docs: http://localhost:8000/docs
```

### 8. Frontend

```bash
cd frontend
npm install
npm start
# http://localhost:3000
```

## Wydajnosc modelu

| Metryka       | Wartosc |
|---------------|---------|
| R² (log)      | TBD     |
| MAPE          | TBD     |
| MAE           | TBD     |
| Wyceny ±10%   | TBD     |
| Wyceny ±20%   | TBD     |

*Uzupelnij po treningu modelu*

## API Reference

### POST /v1/valuate

```bash
curl -X POST http://localhost:8000/v1/valuate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: demo_test_key" \
  -d '{
    "postcode": "3011AA",
    "huisnummer": 42,
    "oppervlakte_m2": 85,
    "energielabel": "B",
    "bouwjaar": 1985
  }'
```

Odpowiedz:
```json
{
  "estimated_value": 385000,
  "confidence_low": 339000,
  "confidence_high": 431000,
  "price_per_m2": 4529,
  "top_factors": [...],
  "comparable_properties": [...],
  "model_version": "xgboost_v1",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Dane publiczne (bezplatne)

| Zrodlo | Dane | URL |
|--------|------|-----|
| BAG (Kadaster) | Adresy, metraz, rok budowy | api.bag.kadaster.nl |
| WOZ Register | Wartosci podatkowe | wozregister.nl |
| EP-online | Klasy energetyczne | ep-online.nl |
| CBS Statline | Dane demograficzne | opendata.cbs.nl |
| OpenStreetMap | POI, spatial | nominatim.osm.org |

## Testy

```bash
pytest tests/ -v
```

## Autor

Zuzanna Schleifer · TU Delft · MSc Big Data + MSc Architecture
[LinkedIn](https://linkedin.com/in/zuzanna-schleifer) · [GitHub](https://github.com/Zuzanna-Schleifer)
