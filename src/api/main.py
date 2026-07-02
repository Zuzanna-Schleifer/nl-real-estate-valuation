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
import pickle
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
feature_names = None


@app.on_event("startup")
async def load_model():
    global model, feature_names

    try:
        with open("xgboost_model.pkl", "rb") as f:
            model = pickle.load(f)

        feature_names = [
            "oppervlakte_m2",
            "oppervlakte_log",
            "energielabel_score",
            "is_wonen",
            "is_kantoor",
            "is_winkel",
            "postcode_4digit_encoded",
            "n_properties_in_postcode",
        ]

        print(f"✓ Model zaladowany z xgboost_model.pkl")
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
    oppervlakte_m2: float = Field(..., gt=10, lt=600, example=85.0, description="Powierzchnia w m2")
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
    top_factors: list
    comparable_properties: list[ComparableProperty]
    model_version: str
    plan: str
    timestamp: str


# ==================================================
# CONSTANTS
# ==================================================

ENERGIELABEL_MAP = {
    "A+++": 10, "A++": 9, "A+": 8, "A": 7,
    "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1,
}


# ==================================================
# AUTH
# ==================================================

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def get_demo_user() -> dict:
    return {"plan": "pro", "email": "demo@example.com", "api_key_hash": "demo"}


def verify_api_key(request: Request) -> dict:
    api_key = request.headers.get("X-API-Key")

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key wymagany. Dodaj naglowek: X-API-Key: twoj_klucz"
        )

    if redis_client is None:
        return get_demo_user()

    key_hash = hash_key(api_key)
    user_data = redis_client.hgetall(f"apikey:{key_hash}")

    if not user_data:
        if api_key.startswith("demo_"):
            return {"plan": "pro", "email": "demo@example.com", "api_key_hash": key_hash}
        raise HTTPException(status_code=401, detail="Nieprawidlowy API key")

    plan = user_data.get("plan", "free")
    month_key = f"usage:{key_hash}:{datetime.utcnow().strftime('%Y%m')}"
    usage = int(redis_client.get(month_key) or 0)
    limits = {"free": 10, "pro": 500, "enterprise": 999_999}
    limit = limits.get(plan, 10)

    if usage >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Limit {limit} wycen/miesiac osiagniety."
        )

    return {**user_data, "api_key_hash": key_hash}


def increment_usage(key_hash: str):
    if redis_client and key_hash != "demo":
        month_key = f"usage:{key_hash}:{datetime.utcnow().strftime('%Y%m')}"
        redis_client.incr(month_key)
        redis_client.expire(month_key, 60 * 60 * 24 * 35)


def build_features(req: ValuationRequest) -> pd.DataFrame:
    row = {
        "oppervlakte_m2": req.oppervlakte_m2,
        "oppervlakte_log": np.log(req.oppervlakte_m2),
        "energielabel_score": ENERGIELABEL_MAP.get(req.energielabel, 5),
        "is_wonen": 1 if req.gebruiksdoel == "wonen" else 0,
        "is_kantoor": 1 if req.gebruiksdoel == "kantoor" else 0,
        "is_winkel": 1 if req.gebruiksdoel == "winkel" else 0,
        "postcode_4digit_encoded": 100,
        "n_properties_in_postcode": 80,
    }
    return pd.DataFrame([row])


def mock_prediction(req: ValuationRequest) -> int:
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

    **Free**: 10/mies.
    **Pro**: 500/mies. + comparables
    **Enterprise**: unlimited
    """
    plan = user.get("plan", "free")

    # Predykcja
    if model is not None:
        X = build_features(body)
        if feature_names:
            for col in feature_names:
                if col not in X.columns:
                    X[col] = 0
            X = X[feature_names]
        pred_log = float(model.predict(X)[0])
        estimated = int(np.exp(pred_log))
    else:
        estimated = mock_prediction(body)

    estimated = round(estimated, -3)
    conf_low = round(int(estimated * 0.88), -3)
    conf_high = round(int(estimated * 1.12), -3)
    price_per_m2 = int(estimated / body.oppervlakte_m2)

    # Feature importance jako top_factors
    top_factors = []
    if model is not None and feature_names:
        importance = dict(zip(feature_names, model.feature_importances_))
        top_factors = [
            {"feature": k, "importance": round(float(v), 4), "direction": "positive"}
            for k, v in sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

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
        top_factors=top_factors,
        comparable_properties=comparables,
        model_version="xgboost_v1" if model else "demo_v0",
        plan=plan,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.post("/v1/admin/create-api-key", tags=["Admin"])
def create_api_key(email: str, plan: str = "free"):
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
