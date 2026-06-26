"""
TYDZIEN 3 - KROK 3
Great Expectations: walidacja jakosci danych w mart_features
Generuje raport HTML po kazdym uruchomieniu DAG.
"""

import great_expectations as gx
import snowflake.connector
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("secrets.env")


def get_snowflake_sample(n_rows: int = 1000) -> pd.DataFrame:
    """Pobiera probke z mart_features do walidacji."""
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database="AVM_DB",
        warehouse="AVM_WH",
        schema="MART",
    )

    query = f"""
        SELECT *
        FROM MART_FEATURES
        SAMPLE ({n_rows} ROWS)
    """

    df = pd.read_sql(query, conn)
    conn.close()

    df.columns = df.columns.str.lower()
    print(f"GE: Pobrano {len(df)} rekordow do walidacji")
    return df


def run_ge_validation():
    """
    Uruchamia suite testow Great Expectations na mart_features.
    Jesli testy nie przesjda - rzuca ValueError (zatrzymuje DAG).
    """
    print("\n=== Great Expectations Validation ===")

    context = gx.get_context()

    df = get_snowflake_sample(1000)

    # Datasource
    datasource = context.sources.add_or_update_pandas(name="snowflake_mart")
    asset = datasource.add_dataframe_asset(name="mart_features")
    batch_request = asset.build_batch_request(dataframe=df)

    # Suite
    suite_name = "avm_mart_suite"
    try:
        suite = context.get_expectation_suite(suite_name)
    except Exception:
        suite = context.add_expectation_suite(suite_name)

    validator = context.get_validator(
        batch_request=batch_request,
        expectation_suite_name=suite_name,
    )

    # =============================================
    # TESTY JAKOSCI DANYCH
    # =============================================

    # 1. Klucz glowny
    validator.expect_column_values_to_not_be_null("bag_id")
    validator.expect_column_values_to_be_unique("bag_id")

    # 2. Target variable - zakres cenowy dla NL
    validator.expect_column_values_to_not_be_null("target_price")
    validator.expect_column_values_to_be_between(
        column="target_price",
        min_value=50_000,
        max_value=10_000_000,
        mostly=0.99,
    )

    # 3. Metraz - realistyczny zakres
    validator.expect_column_values_to_not_be_null("oppervlakte_m2")
    validator.expect_column_values_to_be_between(
        column="oppervlakte_m2",
        min_value=15,
        max_value=500,
        mostly=0.99,
    )

    # 4. Energielabel score - zakres 1-10
    validator.expect_column_values_to_be_between(
        column="energielabel_score",
        min_value=1,
        max_value=10,
        mostly=0.95,
    )

    # 5. Uzytkowan - tylko dozwolone wartosci
    validator.expect_column_values_to_be_in_set(
        column="gebruiksdoel",
        value_set=["wonen", "kantoor", "winkel", "industrie", "overig"],
        mostly=0.99,
    )

    # 6. Postcode - format NL
    validator.expect_column_values_to_match_regex(
        column="postcode",
        regex=r"^\d{4}[A-Z]{2}$",
        mostly=0.95,
    )

    # 7. Kompletnosc - wijk data (80% musi byc wypelnione)
    validator.expect_column_values_to_not_be_null(
        column="wijk_gemiddeld_inkomen",
        mostly=0.80,
    )

    # 8. Log ceny - spójnosc z cena
    validator.expect_column_pair_values_to_be_equal(
        column_A="target_price_log",
        column_B="target_price",
        # Nie rowne - tylko sprawdz ze obydwie sa not null gdy target_price not null
    )
    # Sprawdz ze log price jest rozsdny (ln(50000) ~ 10.8, ln(10000000) ~ 16.1)
    validator.expect_column_values_to_be_between(
        column="target_price_log",
        min_value=10.0,
        max_value=17.0,
        mostly=0.99,
    )

    # 9. Rok budowy - zakres historyczny
    validator.expect_column_values_to_be_between(
        column="bouwjaar",
        min_value=1600,
        max_value=2024,
        mostly=0.90,
    )

    # 10. Liczba rekordow (alarm jesli dane spadna o 50%)
    validator.expect_table_row_count_to_be_between(
        min_value=100,
        max_value=10_000_000,
    )

    validator.save_expectation_suite(discard_failed_expectations=False)

    # Checkpoint i wyniki
    checkpoint = context.add_or_update_checkpoint(
        name="avm_daily_checkpoint",
        validator=validator,
    )

    result = checkpoint.run()
    context.build_data_docs()

    # Podsumowanie
    total = 0
    passed = 0
    failed_tests = []

    for run_result in result.run_results.values():
        validation_result = run_result.get("validation_result", {})
        results = validation_result.get("results", [])

        for r in results:
            total += 1
            if r.get("success"):
                passed += 1
            else:
                exp_type = r.get("expectation_config", {}).get("expectation_type", "")
                col = r.get("expectation_config", {}).get("kwargs", {}).get("column", "table")
                failed_tests.append(f"{exp_type}({col})")

    print(f"\nGE Results: {passed}/{total} testow przeszlo")

    if failed_tests:
        print("Nieudane testy:")
        for t in failed_tests:
            print(f"  ❌ {t}")

    if not result.success:
        raise ValueError(
            f"Data quality validation FAILED: {len(failed_tests)} testow nie przeszlo.\n"
            f"Sprawdz raport: great_expectations/uncommitted/data_docs/local_site/index.html"
        )

    print("✓ Wszystkie testy GE przeszly")
    return result


if __name__ == "__main__":
    run_ge_validation()
