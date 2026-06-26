"""
TYDZIEN 5
Pelny pipeline treningowy:
XGBoost + Optuna HPO + SHAP explainability + MLflow tracking

Po uruchomieniu:
- Otwórz MLflow UI: http://localhost:5000
- Znajdz experiment: dutch_avm_xgboost
- Sprawdz metryki, SHAP importance, model artifact
"""

import xgboost as xgb
import optuna
import mlflow
import mlflow.xgboost
import shap
import pickle
import pandas as pd
import numpy as np
import snowflake.connector
import os
import warnings
from sklearn.model_selection import train_test_split, cross_val_score, KFold
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import LabelEncoder
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv("secrets.env")

optuna.logging.set_verbosity(optuna.logging.WARNING)

EXPERIMENT_NAME = "dutch_avm_xgboost"

FEATURE_COLS = [
    # Budynek
    "oppervlakte_m2",
    "oppervlakte_log",
    "energielabel_score",
    "leeftijd_jaar",
    "is_wonen",
    "is_kantoor",
    "is_winkel",
    # Wijk
    "wijk_gemiddeld_inkomen",
    "wijk_gemiddelde_waarde",
    "wijk_pct_eigenaar",
    "wijk_bevolkingsdichtheid",
    # Postcode
    "postcode_4digit_encoded",
    "n_properties_in_postcode",
    "median_woz_in_postcode",
    # Spatial (jesli dostepne)
    "dist_centrum_m",
    "dist_station_m",
    "n_shops_500m",
    "n_schools_1km",
]

TARGET = "target_price_log"


def load_data() -> pd.DataFrame:
    """Laduje mart_features z Snowflake."""
    print("Ladowanie danych z Snowflake...")

    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database="AVM_DB",
        warehouse="AVM_WH",
        schema="MART",
    )

    df = pd.read_sql("""
        SELECT *
        FROM MART_FEATURES
        WHERE target_price IS NOT NULL
          AND oppervlakte_m2 IS NOT NULL
          AND energielabel_score IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 50000
    """, conn)

    conn.close()
    df.columns = df.columns.str.lower()
    print(f"✓ Zaladowano {len(df):,} rekordow, {len(df.columns)} kolumn")
    return df


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """Feature engineering i imputacja."""

    # Enkodowanie postcode (frequency encoding)
    postcode_freq = df["postcode_4digit"].value_counts().to_dict()
    df["postcode_4digit_encoded"] = df["postcode_4digit"].map(postcode_freq).fillna(0)

    # Uzupelnienie spatial features (mediana jesli brakuje z PySpark job)
    spatial_cols = ["dist_centrum_m", "dist_station_m", "n_shops_500m", "n_schools_1km"]
    for col in spatial_cols:
        if col in df.columns and df[col].isna().any():
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val if pd.notna(median_val) else 0)
        elif col not in df.columns:
            # Kolumna nie istnieje - dodaj z wartoscia domyslna
            defaults = {
                "dist_centrum_m": 2500.0,
                "dist_station_m": 800.0,
                "n_shops_500m": 10,
                "n_schools_1km": 3,
            }
            df[col] = defaults[col]

    # Uzupelnienie wijk features
    wijk_cols = ["wijk_gemiddeld_inkomen", "wijk_gemiddelde_waarde",
                 "wijk_pct_eigenaar", "wijk_bevolkingsdichtheid"]
    for col in wijk_cols:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
        else:
            df[col] = 35000.0

    # Dodaj log oppervlakte jesli brakuje
    if "oppervlakte_log" not in df.columns:
        df["oppervlakte_log"] = np.log(df["oppervlakte_m2"].clip(lower=1))

    # One-hot encoding gebruiksdoel
    for col_name, val in [("is_wonen", "wonen"), ("is_kantoor", "kantoor"), ("is_winkel", "winkel")]:
        if col_name not in df.columns and "gebruiksdoel" in df.columns:
            df[col_name] = (df["gebruiksdoel"] == val).astype(int)
        elif col_name not in df.columns:
            df[col_name] = 0

    # Wiek budynku
    if "leeftijd_jaar" not in df.columns and "bouwjaar" in df.columns:
        df["leeftijd_jaar"] = 2024 - df["bouwjaar"].clip(lower=1600, upper=2024)
        df["leeftijd_jaar"] = df["leeftijd_jaar"].fillna(df["leeftijd_jaar"].median())
    elif "leeftijd_jaar" not in df.columns:
        df["leeftijd_jaar"] = 50.0

    # Uzupelnienie n_properties_in_postcode i median_woz_in_postcode
    if "n_properties_in_postcode" not in df.columns:
        df["n_properties_in_postcode"] = 100
    if "median_woz_in_postcode" not in df.columns:
        df["median_woz_in_postcode"] = df.get("target_price", pd.Series([300000])).median()

    return df


def get_available_features(df: pd.DataFrame) -> list:
    """Zwraca liste dostepnych kolumn z FEATURE_COLS."""
    available = [c for c in FEATURE_COLS if c in df.columns]
    missing = [c for c in FEATURE_COLS if c not in df.columns]

    print(f"Dostepne features: {len(available)}/{len(FEATURE_COLS)}")
    if missing:
        print(f"Brakujace: {missing}")

    return available


def optuna_hpo(X_train, y_train, n_trials: int = 50) -> dict:
    """Optuna hyperparameter optimization dla XGBoost."""
    print(f"\nOptuna HPO: {n_trials} trials...")

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 200, 1000),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 7),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 1.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "tree_method": "hist",
            "random_state": 42,
            "n_jobs": -1,
        }

        model = xgb.XGBRegressor(**params)
        kf = KFold(n_splits=5, shuffle=True, random_state=42)
        scores = cross_val_score(model, X_train, y_train, cv=kf, scoring="r2", n_jobs=-1)

        return scores.mean()

    study = optuna.create_study(
        direction="maximize",
        study_name="xgb_avm_hpo",
        sampler=optuna.samplers.TPESampler(seed=42),
    )

    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best = study.best_params
    best_r2 = study.best_value

    print(f"\n✓ Najlepsze R² (5-fold CV): {best_r2:.4f}")
    print(f"  n_estimators: {best.get('n_estimators')}")
    print(f"  max_depth: {best.get('max_depth')}")
    print(f"  learning_rate: {best.get('learning_rate'):.4f}")

    # Dodaj stale parametry
    best.update({"tree_method": "hist", "random_state": 42, "n_jobs": -1})

    return best, best_r2


def evaluate(model, X_test, y_test_log) -> dict:
    """Oblicza metryki na zbiorze testowym."""
    y_pred_log = model.predict(X_test)

    # Odwroc logarytm dla metryk na oryginalnej skali
    y_pred = np.exp(y_pred_log)
    y_test = np.exp(y_test_log)

    metrics = {
        "r2_log": float(r2_score(y_test_log, y_pred_log)),
        "r2_original": float(r2_score(y_test, y_pred)),
        "mae_eur": float(mean_absolute_error(y_test, y_pred)),
        "rmse_eur": float(np.sqrt(mean_squared_error(y_test, y_pred))),
        "mape_pct": float(np.mean(np.abs((y_test - y_pred) / y_test)) * 100),
        "median_ae_eur": float(np.median(np.abs(y_test - y_pred))),
        "pct_within_10": float(np.mean(np.abs((y_test - y_pred) / y_test) < 0.10) * 100),
        "pct_within_20": float(np.mean(np.abs((y_test - y_pred) / y_test) < 0.20) * 100),
        "n_test": int(len(y_test)),
    }

    print("\n=== Model Performance ===")
    print(f"R² (log price):  {metrics['r2_log']:.4f}")
    print(f"R² (EUR price):  {metrics['r2_original']:.4f}")
    print(f"MAE:             €{metrics['mae_eur']:,.0f}")
    print(f"RMSE:            €{metrics['rmse_eur']:,.0f}")
    print(f"MAPE:            {metrics['mape_pct']:.2f}%")
    print(f"Median AE:       €{metrics['median_ae_eur']:,.0f}")
    print(f"Wyceny w ±10%:  {metrics['pct_within_10']:.1f}%")
    print(f"Wyceny w ±20%:  {metrics['pct_within_20']:.1f}%")

    # Benchmark
    if metrics["r2_log"] >= 0.82:
        print(f"\n✓ BENCHMARK SPELNIONY: R²={metrics['r2_log']:.4f} >= 0.82")
    else:
        print(f"\n⚠ R²={metrics['r2_log']:.4f} < 0.82 - potrzebujesz wiecej danych lub lepszych features")

    return metrics


def compute_shap(model, X_train_sample, X_test_sample, feature_names: list) -> dict:
    """Oblicza SHAP values i tworzy ranking cech."""
    print("\nObliczam SHAP values...")

    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X_test_sample)

    # Feature importance (mean |SHAP|)
    importance = pd.DataFrame({
        "feature": feature_names,
        "mean_abs_shap": np.abs(shap_vals).mean(axis=0),
        "mean_shap": shap_vals.mean(axis=0),
    }).sort_values("mean_abs_shap", ascending=False)

    print("\n=== Top 10 Feature Importance (SHAP) ===")
    print(importance.head(10)[["feature", "mean_abs_shap"]].to_string(index=False))

    return {
        "explainer": explainer,
        "shap_values": shap_vals,
        "feature_importance": importance.to_dict(orient="records"),
    }


def run_training():
    """Pelny pipeline treningowy z MLflow tracking."""

    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment(EXPERIMENT_NAME)

    with mlflow.start_run(run_name="xgboost_optuna_v1") as run:
        run_id = run.info.run_id
        print(f"\nMLflow Run ID: {run_id}")

        # 1. Dane
        df = load_data()
        df = preprocess(df)
        features = get_available_features(df)

        X = df[features].copy()
        y = df[TARGET].copy()

        # Usun wiersze z NaN
        mask = X.notna().all(axis=1) & y.notna()
        X, y = X[mask], y[mask]
        print(f"Czyste dane: {len(X):,} rekordow")

        mlflow.log_params({
            "n_samples": len(X),
            "n_features": len(features),
            "target": TARGET,
            "gemeente": "rotterdam",
        })

        # 2. Split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.20, random_state=42
        )
        print(f"Train: {len(X_train):,} | Test: {len(X_test):,}")

        # 3. HPO
        best_params, cv_r2 = optuna_hpo(X_train, y_train, n_trials=50)
        mlflow.log_params(best_params)
        mlflow.log_metric("cv_r2_best", cv_r2)

        # 4. Trening finalnego modelu
        print("\nTrenuję finalny model...")
        model = xgb.XGBRegressor(**best_params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=100,
        )

        # 5. Ewaluacja
        metrics = evaluate(model, X_test, y_test)
        mlflow.log_metrics(metrics)

        # 6. SHAP
        shap_results = compute_shap(
            model,
            X_train.sample(min(500, len(X_train)), random_state=42),
            X_test.sample(min(200, len(X_test)), random_state=42),
            features,
        )

        mlflow.log_dict(
            {"feature_importance": shap_results["feature_importance"]},
            "artifacts/shap_importance.json"
        )

        # 7. Zapisz model
        mlflow.xgboost.log_model(model, "xgboost_model")

        # 8. Zapisz explainer (dla API)
        explainer_path = "shap_explainer.pkl"
        with open(explainer_path, "wb") as f:
            pickle.dump(shap_results["explainer"], f)
        mlflow.log_artifact(explainer_path)

        # 9. Zapisz feature list (dla API)
        mlflow.log_dict({"features": features}, "artifacts/feature_list.json")

        print(f"\n{'='*50}")
        print(f"✓ Training zakończony!")
        print(f"  MLflow: http://localhost:5000/#/experiments")
        print(f"  Run ID: {run_id}")
        print(f"\nWklej do secrets.env:")
        print(f"  MLFLOW_MODEL_RUN_ID={run_id}")
        print(f"{'='*50}")

        return model, shap_results["explainer"], metrics, run_id


if __name__ == "__main__":
    model, explainer, metrics, run_id = run_training()
