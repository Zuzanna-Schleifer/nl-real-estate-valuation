"""
TYDZIEN 2 - KROK 5
Ladowanie danych z AWS S3 do Snowflake przez COPY INTO.
Tworzy tabele RAW i stage S3.
"""

import snowflake.connector
import os
from dotenv import load_dotenv

load_dotenv("secrets.env")


def get_conn():
    """Zwraca polaczenie Snowflake."""
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database=os.getenv("SNOWFLAKE_DATABASE", "AVM_DB"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "AVM_WH"),
        schema="RAW",
    )


def create_s3_stage(conn):
    """
    Tworzy zewnetrzny stage S3 w Snowflake.
    Stage = polaczenie Snowflake <-> S3 bucket.
    """
    cursor = conn.cursor()

    aws_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    bucket = os.getenv("S3_BUCKET")

    cursor.execute(f"""
        CREATE STAGE IF NOT EXISTS AVM_DB.RAW.S3_RAW_STAGE
        URL = 's3://{bucket}/'
        CREDENTIALS = (
            AWS_KEY_ID = '{aws_key}'
            AWS_SECRET_KEY = '{aws_secret}'
        )
        FILE_FORMAT = (
            TYPE = 'JSON'
            STRIP_OUTER_ARRAY = FALSE
            STRIP_NULL_VALUES = FALSE
        )
        COMMENT = 'Dutch AVM raw data lake S3 stage'
    """)

    conn.commit()
    print("✓ S3 Stage utworzony: AVM_DB.RAW.S3_RAW_STAGE")


def create_raw_tables(conn):
    """Tworzy wszystkie tabele RAW w Snowflake."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS AVM_DB.RAW.BAG_ADRESSEN (
            bag_id              VARCHAR(50),
            straatnaam          VARCHAR(200),
            huisnummer          INTEGER,
            postcode            VARCHAR(10),
            stad                VARCHAR(100),
            gemeente            VARCHAR(100),
            oppervlakte         FLOAT,
            gebruiksdoelen      VARIANT,
            status              VARCHAR(100),
            bouwjaar            INTEGER,
            raw_json            VARIANT,
            s3_key              VARCHAR(500),
            loaded_at           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    print("  ✓ BAG_ADRESSEN")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS AVM_DB.RAW.WOZ_WAARDEN (
            woz_object_nummer   VARCHAR(50),
            postcode            VARCHAR(10),
            huisnummer          INTEGER,
            woz_waarde          INTEGER,
            peildatum           VARCHAR(20),
            gebruikscode        VARCHAR(10),
            is_synthetic        BOOLEAN,
            raw_json            VARIANT,
            loaded_at           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    print("  ✓ WOZ_WAARDEN")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS AVM_DB.RAW.EP_ONLINE_LABELS (
            postcode            VARCHAR(10),
            huisnummer          INTEGER,
            energielabel        VARCHAR(10),
            energieindex        FLOAT,
            registratiedatum    VARCHAR(20),
            gebouwtype          VARCHAR(100),
            is_synthetic        BOOLEAN,
            loaded_at           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    print("  ✓ EP_ONLINE_LABELS")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS AVM_DB.RAW.CBS_WIJK_DATA (
            wijk_code                   VARCHAR(20),
            wijk_naam                   VARCHAR(100),
            gemeente                    VARCHAR(100),
            gemiddelde_woningwaarde     FLOAT,
            gemiddeld_inkomen           FLOAT,
            pct_eigenaar                FLOAT,
            bevolkingsdichtheid         FLOAT,
            inwoners                    INTEGER,
            oppervlakte_km2             FLOAT,
            is_synthetic                BOOLEAN,
            loaded_at                   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    print("  ✓ CBS_WIJK_DATA")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS AVM_DB.RAW.TRANSACTIONS_STREAM (
            transaction_id          VARCHAR(50) PRIMARY KEY,
            bag_id                  VARCHAR(50),
            postcode                VARCHAR(10),
            stad                    VARCHAR(100),
            oppervlakte_m2          FLOAT,
            energielabel            VARCHAR(10),
            gebruiksdoel            VARCHAR(50),
            transaction_price       INTEGER,
            model_price             INTEGER,
            price_deviation_pct     FLOAT,
            transaction_timestamp   TIMESTAMP_NTZ,
            kafka_consumed_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    print("  ✓ TRANSACTIONS_STREAM")

    conn.commit()
    print("\n✓ Wszystkie tabele RAW utworzone")


def copy_s3_to_snowflake(conn, s3_key: str, table_name: str):
    """
    Laduje jeden plik JSON Lines z S3 do tabeli Snowflake.
    Uzywamy COPY INTO - natywny mechanizm Snowflake dla bulk load.
    """
    cursor = conn.cursor()

    sql = f"""
        COPY INTO AVM_DB.RAW.{table_name}
        FROM @AVM_DB.RAW.S3_RAW_STAGE/{s3_key}
        FILE_FORMAT = (
            TYPE = 'JSON'
            STRIP_OUTER_ARRAY = FALSE
        )
        MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
        ON_ERROR = 'CONTINUE'
        PURGE = FALSE
    """

    cursor.execute(sql)
    results = cursor.fetchall()

    rows_loaded = sum(r[3] for r in results) if results else 0
    print(f"  COPY INTO {table_name}: {rows_loaded} wierszy zaladowanych")
    conn.commit()
    return rows_loaded


def run_initial_setup():
    """
    Jednorazowy setup: tworzy stage i tabele.
    Uruchom raz przed pierwszym DAG run.
    """
    print("\n=== Snowflake Initial Setup ===")
    conn = get_conn()

    print("\n1. Tworzenie S3 Stage...")
    create_s3_stage(conn)

    print("\n2. Tworzenie tabel RAW...")
    create_raw_tables(conn)

    conn.close()
    print("\n✓ Setup zakończony - mozna uruchamiac DAG")


def load_s3_to_snowflake(s3_key: str, table_name: str):
    """Wrapper dla Airflow PythonOperator."""
    conn = get_conn()
    rows = copy_s3_to_snowflake(conn, s3_key, table_name)
    conn.close()
    return rows


if __name__ == "__main__":
    run_initial_setup()
