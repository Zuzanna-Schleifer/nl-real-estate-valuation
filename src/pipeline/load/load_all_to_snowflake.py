import snowflake.connector
import json
import os
from dotenv import load_dotenv

load_dotenv("secrets.env")

conn = snowflake.connector.connect(
    account=os.getenv("SNOWFLAKE_ACCOUNT"),
    user=os.getenv("SNOWFLAKE_USER"),
    password=os.getenv("SNOWFLAKE_PASSWORD"),
    warehouse="AVM_WH",
    database="AVM_DB",
    schema="RAW",
    role="AVM_ROLE",
    login_timeout=30,
    network_timeout=30
)
print("Polaczono ze Snowflake")
cursor = conn.cursor()

# Znajdz pliki lokalnie
data_dir = "data"
os.makedirs(data_dir, exist_ok=True)

def load_jsonl(filepath):
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

# BAG
bag_files = [f for f in os.listdir(data_dir) if f.startswith("bag_")]
print(f"Znalezione pliki BAG: {bag_files}")
if bag_files:
    records = load_jsonl(os.path.join(data_dir, bag_files[0]))
    for r in records[:500]:
        cursor.execute(
            "INSERT INTO AVM_DB.RAW.BAG_ADRESSEN (bag_id, straatnaam, huisnummer, postcode, stad, gemeente, oppervlakte, bouwjaar) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (r.get("adresseerbaarObjectIdentificatie",""), r.get("openbareruimtenaam",""), r.get("huisnummer",0), r.get("postcode",""), r.get("woonplaatsnaam",""), r.get("gemeente",""), r.get("oppervlakte",0), r.get("bouwjaar",1970))
        )
    conn.commit()
    print(f"BAG: {min(500, len(records))} rekordow zaladowanych")
else:
    print("Brak plikow BAG w data/")

# EP-online
ep_files = [f for f in os.listdir(data_dir) if f.startswith("ep_")]
if ep_files:
    records = load_jsonl(os.path.join(data_dir, ep_files[0]))
    for r in records[:500]:
        cursor.execute(
            "INSERT INTO AVM_DB.RAW.EP_ONLINE_LABELS (postcode, huisnummer, energielabel, energieindex, gebouwtype, is_synthetic) VALUES (%s, %s, %s, %s, %s, %s)",
            (r.get("postcode",""), r.get("huisnummer",1), r.get("energielabel",""), r.get("energieindex",1.0), r.get("gebouwtype",""), True)
        )
    conn.commit()
    print(f"EP-online: {min(500, len(records))} rekordow zaladowanych")
else:
    print("Brak plikow EP w data/")

# CBS
cbs_files = [f for f in os.listdir(data_dir) if f.startswith("cbs_")]
if cbs_files:
    records = load_jsonl(os.path.join(data_dir, cbs_files[0]))
    for r in records:
        cursor.execute(
            "INSERT INTO AVM_DB.RAW.CBS_WIJK_DATA (wijk_code, wijk_naam, gemeente, gemiddelde_woningwaarde, gemiddeld_inkomen, pct_eigenaar, bevolkingsdichtheid, inwoners, is_synthetic) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (r.get("wijk_code",""), r.get("wijk_naam",""), r.get("gemeente",""), r.get("gemiddelde_woningwaarde",0), r.get("gemiddeld_inkomen",0), r.get("pct_eigenaar",0), r.get("bevolkingsdichtheid",0), r.get("inwoners",0), True)
        )
    conn.commit()
    print(f"CBS: {len(records)} wijken zaladowanych")
else:
    print("Brak plikow CBS w data/")

conn.close()
print("Gotowe!")