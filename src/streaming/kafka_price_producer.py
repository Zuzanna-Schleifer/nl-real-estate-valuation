"""
TYDZIEN 4 - KROK 2
Kafka producer: symuluje real-time stream transakcji nieruchomosci.
Topic: avm.property.transactions
Broker: localhost:9092 (Docker)

Uruchomienie:
  python src/streaming/kafka_price_producer.py
"""

from confluent_kafka import Producer
import json
import time
import random
import os
import snowflake.connector
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("secrets.env")

KAFKA_TOPIC = "avm.property.transactions"
KAFKA_BROKER = "localhost:9092"


def create_producer() -> Producer:
    return Producer({
        "bootstrap.servers": KAFKA_BROKER,
        "client.id": "avm-transaction-producer-v1",
        "acks": "all",
        "retries": 3,
    })


def load_properties_from_snowflake(n: int = 500) -> list:
    """Pobiera probke nieruchomosci z Snowflake jako baze dla transakcji."""
    print("Ladowanie nieruchomosci z Snowflake...")

    try:
        conn = snowflake.connector.connect(
            account=os.getenv("SNOWFLAKE_ACCOUNT"),
            user=os.getenv("SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            database="AVM_DB",
            warehouse="AVM_WH",
            schema="MART",
        )

        df = pd.read_sql(f"""
            SELECT
                bag_id, postcode, stad,
                oppervlakte_m2, energielabel,
                target_price, gebruiksdoel
            FROM MART_FEATURES
            WHERE target_price IS NOT NULL
            ORDER BY RANDOM()
            LIMIT {n}
        """, conn)

        conn.close()
        print(f"✓ Zaladowano {len(df)} nieruchomosci")
        return df.to_dict(orient="records")

    except Exception as e:
        print(f"Snowflake niedostepne ({e}) - uzywam syntetycznych danych")
        return generate_synthetic_properties(n)


def generate_synthetic_properties(n: int = 200) -> list:
    """Fallback: syntetyczne nieruchomosci gdy Snowflake niedostepne."""
    postcodes = ["3011AA", "3012BB", "3013CC", "3014DD", "3021EE",
                 "3022FF", "3031GG", "3041HH", "3051II", "3052JJ"]
    labels = ["A", "A+", "B", "B", "C", "C", "D"]
    uses = ["wonen"] * 8 + ["kantoor", "winkel"]

    props = []
    for i in range(n):
        area = random.randint(45, 180)
        base_price = area * random.randint(3000, 6000)
        props.append({
            "bag_id": f"BAG_SYNTH_{i:06d}",
            "postcode": random.choice(postcodes),
            "stad": "Rotterdam",
            "oppervlakte_m2": area,
            "energielabel": random.choice(labels),
            "target_price": base_price,
            "gebruiksdoel": random.choice(uses),
        })
    return props


def simulate_transaction(prop: dict) -> dict:
    """
    Simuleert een verkooptransactie.
    Prijs = model prediction +/- 5% marktgeluid.
    """
    base_price = prop.get("target_price", 300_000)

    # Rynkowy szum: ±5%
    noise = random.gauss(mu=0.0, sigma=0.025)
    transaction_price = int(base_price * (1 + noise))

    # Klucz czasowy dla idempotentnosci
    ts = datetime.utcnow()
    txn_id = f"TXN{ts.strftime('%Y%m%d%H%M%S')}{random.randint(100,999)}"

    return {
        "transaction_id": txn_id,
        "bag_id": prop.get("bag_id"),
        "postcode": prop.get("postcode"),
        "stad": prop.get("stad"),
        "oppervlakte_m2": prop.get("oppervlakte_m2"),
        "energielabel": prop.get("energielabel"),
        "gebruiksdoel": prop.get("gebruiksdoel"),
        "transaction_price": transaction_price,
        "model_price": int(base_price),
        "price_deviation_pct": round(noise * 100, 2),
        "transaction_timestamp": ts.isoformat() + "Z",
        "source": "avm_simulator_v1",
    }


def delivery_callback(err, msg):
    if err:
        print(f"  ❌ Delivery failed: {err}")
    else:
        data = json.loads(msg.value().decode())
        print(
            f"  ✓ [{msg.partition()}@{msg.offset()}] "
            f"{data['transaction_id']} | "
            f"{data['postcode']} | "
            f"€{data['transaction_price']:,}"
        )


def run_producer(interval_seconds: float = 5.0, max_messages: int = None):
    """
    Glowna funkcja producera.

    interval_seconds: czas miedzy transakcjami
    max_messages: None = nieskonczona petla, int = limit
    """
    producer = create_producer()
    properties = load_properties_from_snowflake(500)

    print(f"\n{'='*50}")
    print(f"Kafka Producer uruchomiony")
    print(f"Topic:    {KAFKA_TOPIC}")
    print(f"Broker:   {KAFKA_BROKER}")
    print(f"Interval: {interval_seconds}s")
    print(f"{'='*50}")
    print("Ctrl+C aby zatrzymac\n")

    count = 0
    try:
        while True:
            if max_messages and count >= max_messages:
                print(f"Osiagnieto limit {max_messages} wiadomosci")
                break

            prop = random.choice(properties)
            txn = simulate_transaction(prop)

            producer.produce(
                topic=KAFKA_TOPIC,
                key=txn["bag_id"].encode("utf-8"),
                value=json.dumps(txn, ensure_ascii=False).encode("utf-8"),
                callback=delivery_callback,
            )

            producer.poll(0)
            count += 1
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        print("\nZatrzymuję producer...")
    finally:
        remaining = producer.flush(timeout=10)
        print(f"✓ Producer zatrzymany. Niewyslane: {remaining}")


if __name__ == "__main__":
    run_producer(interval_seconds=5)
