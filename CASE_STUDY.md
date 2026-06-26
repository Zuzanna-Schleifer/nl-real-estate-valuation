# Case Study — Model Validation on Funda.nl Data

## Cel
Walidacja modelu AVM na rzeczywistych cenach transakcyjnych z holenderskiego rynku nieruchomości.
50 nieruchomości sprzedanych w Rotterdamie w Q1 2024, których ceny są publicznie dostępne na Funda.nl.

---

## Metodologia

### Zbieranie danych referencyjnych
1. Wejdź na `funda.nl/koop/rotterdam/verkocht/`
2. Filtruj: Rotterdam, sprzedane w 2024
3. Zbierz 50 nieruchomości z: adresem, ceną sprzedaży, metrażem, energielabelem, rokiem budowy
4. Zapisz do `data/funda_validation_set.csv`

### Procedura walidacji
```python
import pandas as pd
import numpy as np
import requests

df = pd.read_csv("data/funda_validation_set.csv")
API_URL = "http://localhost:8000/v1/valuate"
API_KEY = "twoj_klucz"

predictions = []
for _, row in df.iterrows():
    response = requests.post(API_URL,
        json={
            "postcode": row["postcode"],
            "huisnummer": int(row["huisnummer"]),
            "oppervlakte_m2": float(row["oppervlakte_m2"]),
            "energielabel": row["energielabel"],
            "bouwjaar": int(row["bouwjaar"]) if pd.notna(row["bouwjaar"]) else None
        },
        headers={"X-API-Key": API_KEY}
    )
    pred = response.json()["estimated_value"]
    predictions.append(pred)

df["avm_prediction"] = predictions
df["absolute_error"] = abs(df["funda_price"] - df["avm_prediction"])
df["pct_error"] = df["absolute_error"] / df["funda_price"] * 100
```

---

## Wyniki

> *Uzupełnij po uruchomieniu walidacji*

| Metryka | Wartość |
|---------|---------|
| R² | — |
| MAPE | — % |
| MAE | €— |
| Median AE | €— |
| % wycen w ±10% | — % |
| % wycen w ±20% | — % |
| N (próba) | 50 |

---

## Przykładowe predykcje

> *Uzupełnij po uruchomieniu walidacji. Adresy zanonimizowane.*

| Wijk | Oppervlakte | Energie | Bouwjaar | Cena Funda | Predykcja AVM | Błąd % |
|------|-------------|---------|----------|------------|---------------|--------|
| Centrum | 92 m² | B | 1965 | — | — | — |
| Kralingen | 110 m² | A | 2005 | — | — | — |
| Delfshaven | 68 m² | C | 1930 | — | — | — |
| Hillegersberg | 145 m² | A+ | 2018 | — | — | — |
| Feijenoord | 75 m² | D | 1955 | — | — | — |

---

## Najważniejsze czynniki (SHAP — średnia po 50 nieruchomościach)

> *Uzupełnij po uruchomieniu walidacji*

| Rank | Feature | Mean |SHAP| |
|------|---------|------------|
| 1 | Oppervlakte (m²) | — |
| 2 | Wijk gemiddeld inkomen | — |
| 3 | Afstand station | — |
| 4 | Energielabel score | — |
| 5 | Medianwaarde postcode | — |

---

## Analiza błędów

### Gdzie model się myli najbardziej
- Nieruchomości luksusowe (>€1M) — zbyt mało danych treningowych
- Historyczne kamienice (bouwjaar <1920) — unikalne cechy trudne do uchwycenia
- Nieruchomości z renowacją — BAG nie zawiera info o stanie technicznym

### Ograniczenia modelu
1. **Brak danych o stanie technicznym** — BAG nie zawiera info o remoncie
2. **WOZ ≠ cena rynkowa** — WOZ jest wyceną podatkową, może odstawać o 5-15%
3. **Zasięg geograficzny** — model trenowany na Rotterdamie, inne miasta mogą dawać gorsze wyniki
4. **Dane czasowe** — model nie uwzględnia cykli rynkowych (boom/recesja)

---

## Reprodukowalność

Pełny notebook walidacyjny: `notebooks/case_study_validation.ipynb`

```bash
jupyter notebook notebooks/case_study_validation.ipynb
```

Dane wejściowe (zanonimizowane): `data/funda_validation_set.csv`

---

## Porównanie z benchmarkami branżowymi

| Benchmark | MAPE | Źródło |
|-----------|------|--------|
| Kadaster AVM (NL) | ~8-12% | Kadaster jaarrapport 2023 |
| Calcasa AVM | ~10% | Publiczne dane |
| **Dutch AVM (ten projekt)** | **—%** | *uzupełnij* |

---

*Ostatnia aktualizacja: uzupełnij po walidacji*
*Autor: Zuzanna Schleifer | TU Delft MSc Big Data + Architecture*
