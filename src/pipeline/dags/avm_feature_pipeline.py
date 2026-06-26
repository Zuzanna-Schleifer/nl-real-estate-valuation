"""
TYDZIEN 3 - KROK 1
Airflow DAG: orchestracja calego pipeline AVM
Extract (S3) -> Load (Snowflake RAW) -> Transform (dbt) -> Validate (GE)

Po uruchomieniu docker compose:
Otwórz: http://localhost:8080 (admin/admin)
Znajdziesz DAG: avm_feature_pipeline
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, "/opt/airflow/project")

default_args = {
    "owner": "avm",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "email_on_retry": False,
}

with DAG(
    dag_id="avm_feature_pipeline",
    default_args=default_args,
    description="Dutch AVM: Extract -> S3 -> Snowflake -> dbt -> Great Expectations",
    schedule_interval="0 6 * * *",  # Codziennie o 6:00 UTC
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["avm", "proptech", "netherlands", "snowflake"],
) as dag:

    # ----------------------------------------------------------
    # START
    # ----------------------------------------------------------
    start = EmptyOperator(task_id="start")

    # ----------------------------------------------------------
    # EXTRACT - pobieranie danych ze zrodel
    # ----------------------------------------------------------
    def extract_bag(**context):
        from src.pipeline.extract.bag_extractor import run_bag_extraction
        s3_key = run_bag_extraction("0599", "rotterdam")
        context["task_instance"].xcom_push(key="bag_s3_key", value=s3_key)
        return s3_key

    def extract_woz(**context):
        from src.pipeline.extract.woz_extractor import run_woz_extraction
        s3_key = run_woz_extraction("0599", "rotterdam")
        context["task_instance"].xcom_push(key="woz_s3_key", value=s3_key)
        return s3_key

    def extract_ep(**context):
        from src.pipeline.extract.ep_online_extractor import run_ep_extraction
        s3_key = run_ep_extraction("0599", "rotterdam")
        context["task_instance"].xcom_push(key="ep_s3_key", value=s3_key)
        return s3_key

    def extract_cbs(**context):
        from src.pipeline.extract.cbs_extractor import run_cbs_extraction
        s3_key = run_cbs_extraction()
        context["task_instance"].xcom_push(key="cbs_s3_key", value=s3_key)
        return s3_key

    task_extract_bag = PythonOperator(
        task_id="extract_bag",
        python_callable=extract_bag,
    )

    task_extract_woz = PythonOperator(
        task_id="extract_woz",
        python_callable=extract_woz,
    )

    task_extract_ep = PythonOperator(
        task_id="extract_ep_online",
        python_callable=extract_ep,
    )

    task_extract_cbs = PythonOperator(
        task_id="extract_cbs",
        python_callable=extract_cbs,
    )

    # ----------------------------------------------------------
    # LOAD - S3 -> Snowflake RAW
    # ----------------------------------------------------------
    def load_bag(**context):
        from src.pipeline.load.snowflake_loader import load_s3_to_snowflake
        s3_key = context["task_instance"].xcom_pull(
            task_ids="extract_bag", key="bag_s3_key"
        )
        return load_s3_to_snowflake(s3_key, "BAG_ADRESSEN")

    def load_woz(**context):
        from src.pipeline.load.snowflake_loader import load_s3_to_snowflake
        s3_key = context["task_instance"].xcom_pull(
            task_ids="extract_woz", key="woz_s3_key"
        )
        return load_s3_to_snowflake(s3_key, "WOZ_WAARDEN")

    def load_ep(**context):
        from src.pipeline.load.snowflake_loader import load_s3_to_snowflake
        s3_key = context["task_instance"].xcom_pull(
            task_ids="extract_ep_online", key="ep_s3_key"
        )
        return load_s3_to_snowflake(s3_key, "EP_ONLINE_LABELS")

    def load_cbs(**context):
        from src.pipeline.load.snowflake_loader import load_s3_to_snowflake
        s3_key = context["task_instance"].xcom_pull(
            task_ids="extract_cbs", key="cbs_s3_key"
        )
        return load_s3_to_snowflake(s3_key, "CBS_WIJK_DATA")

    task_load_bag = PythonOperator(
        task_id="load_bag_snowflake",
        python_callable=load_bag,
    )

    task_load_woz = PythonOperator(
        task_id="load_woz_snowflake",
        python_callable=load_woz,
    )

    task_load_ep = PythonOperator(
        task_id="load_ep_snowflake",
        python_callable=load_ep,
    )

    task_load_cbs = PythonOperator(
        task_id="load_cbs_snowflake",
        python_callable=load_cbs,
    )

    # ----------------------------------------------------------
    # TRANSFORM - dbt ELT (Snowflake-native)
    # ----------------------------------------------------------
    task_dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=(
            "cd /opt/airflow/project/dbt/avm_dbt && "
            "dbt run --profiles-dir . --target dev"
        ),
    )

    task_dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=(
            "cd /opt/airflow/project/dbt/avm_dbt && "
            "dbt test --profiles-dir . --target dev"
        ),
    )

    task_dbt_docs = BashOperator(
        task_id="dbt_docs_generate",
        bash_command=(
            "cd /opt/airflow/project/dbt/avm_dbt && "
            "dbt docs generate --profiles-dir . --target dev"
        ),
    )

    # ----------------------------------------------------------
    # SPATIAL FEATURES - PySpark job
    # ----------------------------------------------------------
    task_spatial = BashOperator(
        task_id="pyspark_spatial_features",
        bash_command=(
            "cd /opt/airflow/project && "
            "python src/pipeline/transform/spatial_features.py"
        ),
    )

    # ----------------------------------------------------------
    # VALIDATE - Great Expectations
    # ----------------------------------------------------------
    task_ge_validate = BashOperator(
        task_id="great_expectations_validate",
        bash_command=(
            "cd /opt/airflow/project && "
            "python src/pipeline/quality/ge_validation.py"
        ),
    )

    # ----------------------------------------------------------
    # END
    # ----------------------------------------------------------
    end = EmptyOperator(task_id="end")

    # ----------------------------------------------------------
    # ZALEŻNOŚCI - kolejnosc wykonania
    # ----------------------------------------------------------
    start >> [task_extract_bag, task_extract_woz, task_extract_ep, task_extract_cbs]

    task_extract_bag >> task_load_bag
    task_extract_woz >> task_load_woz
    task_extract_ep >> task_load_ep
    task_extract_cbs >> task_load_cbs

    [task_load_bag, task_load_woz, task_load_ep, task_load_cbs] >> task_dbt_run
    task_dbt_run >> task_dbt_test >> task_dbt_docs >> task_spatial >> task_ge_validate >> end
