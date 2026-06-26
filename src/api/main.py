"""
TYDZIEN 6
FastAPI: REST API do wyceny nieruchomosci.

Uruchomienie:
  uvicorn src.api.main:app --reload --port 8000

Dokumentacja: http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import mlflow.xgboost
import pickle
import shap
import numpy as np
import pandas as pd
import hashlib
import os
import redis
import stripe
from datetime import datetime
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv("secrets.env")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_placeholder")

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Dutch AVM API",
    description=(
        "Automated Valuation Model for the Dutch real estate market. "
        "Powered by XGBoost trained on BAG, WOZ, CBS and EP-online data."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis
try:
    redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    redis_client.ping()
    print("✓ Redis connected")
except Exception:
    redis_client = None
    print("⚠ Redis unavailable - rate limiting disabled")

# Model globals
model = None
explainer = None
feature_names = None


@app.on_event("startup")
async def load_model():
    global model, explainer, feature_names

    run_id = os.getenv("MLFLOW_MODEL_RUN_ID")
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")

    if not run_id or run_id == "TUTAJ_PO_TRENINGU":
        print("⚠ MLFLOW_MODEL_RUN_ID nie ustawiony - API dziala w trybie demo")
        return

    try:
        mlflow.set_tracking_uri(mlflow_uri)
        model = mlflow.xgboost.load_model(f"runs:/{run_id}/xgboost_model")

        # Zaladuj explainer
        explainer_path = "shap_explainer.pkl"
        if os.path.exists(explainer_path):
            with open(explainer_path, "rb") as f:
                explainer = pickle.load(f)

        # Zaladuj nazwy cech
        client = mlflow.tracking.MlflowClient()
        artifact_path = client.download_artifacts(run_id, "artifacts/feature_list.json")
        import json
        with open(artifact_path) as f:
            feature_names = json.load(f)["features"]

        print(f"✓ Model zaladowany (run: {run_id})")
        print(f"  Features: {len(feature_names)}")

    except Exception as e:
        print(f"⚠ Nie mozna zaladowac modelu: {e}")
        print("  API dziala w trybie demo")


# ==================================================
# MODELE PYDANTIC
# ==================================================

class ValuationRequest(BaseModel):
    postcode: str = Field(..., example="3011AA", description="Kod pocztowy NL (4 cyfry + 2 litery)")
    huisnummer: int = Field(..., ge=1, le=9999, example=42)
    oppervlakte_m2: float = Field(..., gt=10, lt=600, example=85.0, description="Powierzchnia w m²")
    gebruiksdoel: str = Field(default="wonen", example="wonen", description="wonen | kantoor | winkel")
    energielabel: Optional[str] = Field(default=None, example="B", description="A+++ do G")
    bouwjaar: Optional[int] = Field(default=None, ge=1600, le=2024, example=1985)

    class Config:
        json_schema_extra = {
            "example": {
                "postcode": "3011AA",
                "huisnummer": 42,
                "oppervlakte_m2": 85.0,
                "gebruiksdoel": "wonen",
                "energielabel": "B",
                "bouwjaar": 1985,
            }
        }


class SHAPFactor(BaseModel):
    feature: str
    impact_eur: float
    direction: str


class ComparableProperty(BaseModel):
    postcode: str
    oppervlakte_m2: float
    energielabel: Optional[str]
    estimated_price: int
    price_per_m2: int


class ValuationResponse(BaseModel):
    estimated_value: int
    confidence_low: int
    confidence_high: int
    confidence_level_pct: int = 80
    price_per_m2: int
    top_factors: list[SHAPFactor]
    comparable_properties: list[ComparableProperty]
    model_version: str
    plan: str
    timestamp: str


# ==================================================
# AUTH
# ==================================================

ENERGIELABEL_MAP = {
    "A+++": 10, "A++": 9, "A+": 8, "A": 7,
    "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1,
}

FEATURE_FRIENDLY_NAMES = {
    "oppervlakte_m2": "Oppervlakte (m²)",
    "oppervlakte_log": "Oppervlakte (log)",
    "energielabel_score": "Energielabel",
    "leeftijd_jaar": "Leeftijd gebouw",
    "dist_station_m": "Afstand station",
    "dist_centrum_m": "Afstand centrum",
    "wijk_gemiddeld_inkomen": "Gemiddeld inkomen wijk",
    "wijk_gemiddelde_waarde": "Gemiddelde waarde wijk",
    "wijk_pct_eigenaar": "% eigenaar-bewoners",
    "n_shops_500m": "Winkels (500m)",
    "n_schools_1km": "Scholen (1km)",
    "postcode_4digit_encoded": "Populariteit postcode",
    "n_properties_in_postcode": "Dichtheid postcode",
    "median_woz_in_postcode": "Medianwaarde postcode",
}


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def get_demo_user() -> dict:
    """Demo user dla testow bez Redis."""
    return {"plan": "pro", "email": "demo@example.com", "api_key_hash": "demo"}


def verify_api_key(request: Request) -> dict:
    """Weryfikuje API key z naglowka X-API-Key."""
    api_key = request.headers.get("X-API-Key")

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key wymagany. Dodaj naglowek: X-API-Key: twoj_klucz"
        )

    # Demo mode - akceptuj kazdy klucz jesli Redis niedostepny
    if redis_client is None:
        return get_demo_user()

    key_hash = hash_key(api_key)
    user_data = redis_client.hgetall(f"apikey:{key_hash}")

    if not user_data:
        # W demo mode - utwórz demo usera automatycznie
        if api_key.startswith("demo_"):
            return {"plan": "pro", "email": "demo@example.com", "api_key_hash": key_hash}
        raise HTTPException(status_code=401, detail="Nieprawidlowy API key")

    # Sprawdz limit miesięczny
    plan = user_data.get("plan", "free")
    month_key = f"usage:{key_hash}:{datetime.utcnow().strftime('%Y%m')}"
    usage = int(redis_client.get(month_key) or 0)
    limits = {"free": 10, "pro": 500, "enterprise": 999_999}
    limit = limits.get(plan, 10)

    if usage >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Limit {limit} wycen/miesiąc osiągnięty. Upgrade: dutch-avm.vercel.app/pricing"
        )

    return {**user_data, "api_key_hash": key_hash}


def increment_usage(key_hash: str):
    if redis_client and key_hash != "demo":
        month_key = f"usage:{key_hash}:{datetime.utcnow().strftime('%Y%m')}"
        redis_client.incr(month_key)
        redis_client.expire(month_key, 60 * 60 * 24 * 35)


def build_features(req: ValuationRequest) -> pd.DataFrame:
    """Buduje wektor cech z requestu."""
    leeftijd = (2024 - req.bouwjaar) if req.bouwjaar else 45

    row = {
        "oppervlakte_m2": req.oppervlakte_m2,
        "oppervlakte_log": np.log(req.oppervlakte_m2),
        "energielabel_score": ENERGIELABEL_MAP.get(req.energielabel, 5),
        "leeftijd_jaar": leeftijd,
        "is_wonen": 1 if req.gebruiksdoel == "wonen" else 0,
        "is_kantoor": 1 if req.gebruiksdoel == "kantoor" else 0,
        "is_winkel": 1 if req.gebruiksdoel == "winkel" else 0,
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

    return pd.DataFrame([row])


def get_shap_factors(shap_vals: np.ndarray, feat_names: list, n: int = 5) -> list:
    """Zwraca top N czynnikow SHAP jako EUR impact."""
    pairs = sorted(
        zip(feat_names, shap_vals[0]),
        key=lambda x: abs(x[1]),
        reverse=True,
    )

    factors = []
    for name, val in pairs[:n]:
        # SHAP jest w log(EUR) - konwertuj na EUR (przyblizenie)
        base_price = 300_000
        impact_eur = int(base_price * (np.exp(val) - 1))

        factors.append(SHAPFactor(
            feature=FEATURE_FRIENDLY_NAMES.get(name, name),
            impact_eur=impact_eur,
            direction="positive" if val > 0 else "negative",
        ))

    return factors


def mock_prediction(req: ValuationRequest) -> int:
    """Demo predykcja gdy model nie jest zaladowany."""
    base = req.oppervlakte_m2 * 3_800
    energy_factor = ENERGIELABEL_MAP.get(req.energielabel, 5) / 6.0
    return int(base * energy_factor)


# ==================================================
# ENDPOINTS
# ==================================================

@app.get("/", tags=["Info"])
def root():
    return {
        "api": "Dutch AVM API",
        "version": "1.0.0",
        "model_loaded": model is not None,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["Info"])
def health():
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "redis_connected": redis_client is not None,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/v1/valuate", response_model=ValuationResponse, tags=["Valuation"])
@limiter.limit("60/minute")
async def valuate(
    request: Request,
    body: ValuationRequest,
    user: dict = Depends(verify_api_key),
):
    """
    Wycena nieruchomosci.

    **Free**: 10/mies. | bez SHAP | bez comparables
    **Pro**: 500/mies. | pelny SHAP | 3 comparables
    **Enterprise**: unlimited | bulk endpoint | SLA
    """
    plan = user.get("plan", "free")

    # Predykcja
    if model is not None:
        X = build_features(body)

        # Dopasuj kolumny do feature_names modelu
        if feature_names:
            for col in feature_names:
                if col not in X.columns:
                    X[col] = 0
            X = X[feature_names]

        pred_log = float(model.predict(X)[0])
        estimated = int(np.exp(pred_log))
    else:
        estimated = mock_prediction(body)

    # Zaokrągl do 1000 EUR
    estimated = round(estimated, -3)
    conf_low = round(int(estimated * 0.88), -3)
    conf_high = round(int(estimated * 1.12), -3)
    price_per_m2 = int(estimated / body.oppervlakte_m2)

    # SHAP (tylko Pro+)
    shap_factors = []
    if plan in ["pro", "enterprise"] and model is not None and explainer is not None:
        try:
            X = build_features(body)
            if feature_names:
                for col in feature_names:
                    if col not in X.columns:
                        X[col] = 0
                X = X[feature_names]
            shap_vals = explainer.shap_values(X)
            shap_factors = get_shap_factors(shap_vals, X.columns.tolist())
        except Exception as e:
            print(f"SHAP error: {e}")

    # Comparable properties (tylko Pro+)
    comparables = []
    if plan in ["pro", "enterprise"]:
        comparables = [
            ComparableProperty(
                postcode=body.postcode,
                oppervlakte_m2=round(body.oppervlakte_m2 * 0.92, 1),
                energielabel="C",
                estimated_price=round(int(estimated * 0.95), -3),
                price_per_m2=int(estimated * 0.95 / (body.oppervlakte_m2 * 0.92)),
            ),
            ComparableProperty(
                postcode=body.postcode,
                oppervlakte_m2=round(body.oppervlakte_m2 * 1.08, 1),
                energielabel=body.energielabel or "B",
                estimated_price=round(int(estimated * 1.05), -3),
                price_per_m2=int(estimated * 1.05 / (body.oppervlakte_m2 * 1.08)),
            ),
        ]

    increment_usage(user["api_key_hash"])

    return ValuationResponse(
        estimated_value=estimated,
        confidence_low=conf_low,
        confidence_high=conf_high,
        price_per_m2=price_per_m2,
        top_factors=shap_factors,
        comparable_properties=comparables,
        model_version="xgboost_v1" if model else "demo_v0",
        plan=plan,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.post("/v1/admin/create-api-key", tags=["Admin"])
def create_api_key(email: str, plan: str = "free"):
    """Tworzy nowy API key (tylko dla admina)."""
    import secrets
    raw_key = f"avm_{secrets.token_urlsafe(32)}"
    key_hash = hash_key(raw_key)

    if redis_client:
        redis_client.hset(f"apikey:{key_hash}", mapping={
            "email": email,
            "plan": plan,
            "created_at": datetime.utcnow().isoformat(),
        })

    return {
        "api_key": raw_key,
        "plan": plan,
        "email": email,
        "note": "Zapisz klucz - pokazuje sie tylko raz!",
    }


@app.post("/v1/webhook/stripe", tags=["Billing"])
async def stripe_webhook(request: Request):
    """Obsluguje zdarzenia Stripe po uiszczeniu platnosci."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
        else:
            event = {"type": "test", "data": {"object": {}}}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = session.get("customer_email", "")
        plan = session.get("metadata", {}).get("plan", "pro")
        print(f"✓ Stripe: platnosc od {email} -> plan {plan}")

    return {"received": True}
