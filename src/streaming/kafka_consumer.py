"""
TYDZIEN 4 - KROK 3
Kafka consumer: odbiera transakcje i zapisuje do Snowflake.
Uruchamiac rownolegle z producerem w osobnym terminalu.

Terminal 1: python src/streaming/kafka_price_producer.py
Terminal 2: python src/streaming/kafka_consumer.py
"""

from confluent_kafka import Consumer, KafkaError, KafkaException
import json
import os
import snowflake.connector
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("secrets.env")

KAFKA_TOPIC = "avm.property.transactions"
KAFKA_BROKER = "localhost:9092"
GROUP_ID = "avm-transaction-consumer-v1"


def create_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": KAFKA_BROKER,
        "group.id": GROUP_ID,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
        "auto.commit.interval.ms": 5000,
        "session.timeout.ms": 30000,
    })


def get_snowflake_conn():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        database="AVM_DB",
        warehouse="AVM_WH",
        schema="RAW",
    )


def setup_transactions_table(conn):
    """Tworzy tabele TRANSACTIONS_STREAM jesli nie istnieje."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS AVM_DB.RAW.TRANSACTIONS_STREAM (
            transaction_id          VARCHAR(50),
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
            kafka_consumed_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
            kafka_topic             VARCHAR(100),
            kafka_partition         INTEGER,
            kafka_offset            BIGINT
        )
    """)
    conn.commit()
    print("✓ Tabela TRANSACTIONS_STREAM gotowa")


def insert_transaction(conn, txn: dict, partition: int, offset: int):
    """Zapisuje jedna transakcje do Snowflake."""
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO AVM_DB.RAW.TRANSACTIONS_STREAM (
            transaction_id, bag_id, postcode, stad,
            oppervlakte_m2, energielabel, gebruiksdoel,
            transaction_price, model_price, price_deviation_pct,
            transaction_timestamp, kafka_topic, kafka_partition, kafka_offset
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        txn["transaction_id"],
        txn.get("bag_id"),
        txn.get("postcode"),
        txn.get("stad"),
        txn.get("oppervlakte_m2"),
        txn.get("energielabel"),
        txn.get("gebruiksdoel"),
        txn.get("transaction_price"),
        txn.get("model_price"),
        txn.get("price_deviation_pct"),
        txn.get("transaction_timestamp"),
        KAFKA_TOPIC,
        partition,
        offset,
    ))
    conn.commit()


def run_consumer(max_messages: int = None):
    """
    Glowna petla konsumera.
    max_messages: None = nieskonczona petla
    """
    consumer = create_consumer()
    consumer.subscribe([KAFKA_TOPIC])

    conn = get_snowflake_conn()
    setup_transactions_table(conn)

    print(f"\n{'='*50}")
    print(f"Kafka Consumer uruchomiony")
    print(f"Topic:  {KAFKA_TOPIC}")
    print(f"Group:  {GROUP_ID}")
    print(f"Broker: {KAFKA_BROKER}")
    print(f"{'='*50}")
    print("Oczekuje na wiadomosci... (Ctrl+C aby zatrzymac)\n")

    count = 0
    total_value = 0

    try:
        while True:
            if max_messages and count >= max_messages:
                break

            msg = consumer.poll(timeout=1.0)

            if msg is None:
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    print(f"  EOF partition {msg.partition()} @ {msg.offset()}")
                    continue
                elif msg.error().code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
                    print(f"  Topic {KAFKA_TOPIC} nie istnieje jeszcze - czekam...")
                    continue
                else:
                    raise KafkaException(msg.error())

            # Parsuj wiadomosc
            try:
                txn = json.loads(msg.value().decode("utf-8"))
            except json.JSONDecodeError as e:
                print(f"  JSON parse error: {e}")
                continue

            # Zapisz do Snowflake
            try:
                insert_transaction(conn, txn, msg.partition(), msg.offset())
                count += 1
                total_value += txn.get("transaction_price", 0)

                print(
                    f"  ✓ #{count} | {txn['transaction_id']} | "
                    f"{txn.get('postcode', 'N/A')} | "
                    f"€{txn.get('transaction_price', 0):,} | "
                    f"deviatcja: {txn.get('price_deviation_pct', 0):+.1f}%"
                )

                # Statystyki co 10 transakcji
                if count % 10 == 0:
                    avg_price = total_value / count
                    print(f"\n  --- Statystyki ({count} transakcji) ---")
                    print(f"  Srednia cena: €{avg_price:,.0f}")
                    print(f"  Lacznie: €{total_value:,.0f}\n")

            except Exception as e:
                print(f"  Snowflake insert error: {e}")
                # Reconnect
                try:
                    conn = get_snowflake_conn()
                except Exception:
                    pass

    except KeyboardInterrupt:
        print(f"\n\nZatrzymuję consumer po {count} transakcjach")
        if count > 0:
            print(f"Lacznie przetworzone: €{total_value:,.0f}")
    finally:
        consumer.close()
        conn.close()
        print("✓ Consumer zatrzymany")


if __name__ == "__main__":
    run_consumer()
