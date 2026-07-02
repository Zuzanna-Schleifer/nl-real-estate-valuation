import json
import os
import random
import numpy as np

os.makedirs("data", exist_ok=True)

# BAG
straten = ["Coolsingel", "Blaak", "Witte de Withstraat", "Meent", "Hoogstraat"]
postcodes = ["3011AA", "3011AB", "3012BA", "3013CC", "3014DD", "3021EE", "3022FF", "3031GG"]
records = []
for i in range(500):
    records.append({
        "adresseerbaarObjectIdentificatie": f"BAG{i:08d}",
        "openbareruimtenaam": random.choice(straten),
        "huisnummer": random.randint(1, 200),
        "postcode": random.choice(postcodes),
        "woonplaatsnaam": "Rotterdam",
        "gemeente": "Rotterdam",
        "oppervlakte": random.randint(40, 250),
        "bouwjaar": random.randint(1920, 2020),
    })
with open("data/bag_rotterdam.jsonl", "w") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")
print(f"BAG: {len(records)} rekordow zapisanych")

# EP-online
labels = ["A+++","A++","A+","A","B","C","D","E","F","G"]
weights = [0.02,0.03,0.05,0.05,0.18,0.22,0.20,0.12,0.08,0.05]
records = []
for i in range(500):
    records.append({
        "postcode": random.choice(postcodes),
        "huisnummer": random.randint(1, 150),
        "energielabel": random.choices(labels, weights=weights)[0],
        "energieindex": round(random.uniform(0.5, 3.5), 2),
        "gebouwtype": random.choice(["Tussenwoning","Hoekwoning","Appartement"]),
        "is_synthetic": True,
    })
with open("data/ep_rotterdam.jsonl", "w") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")
print(f"EP-online: {len(records)} rekordow zapisanych")

# CBS
wijken = [
    ("WK059900","Centrum"), ("WK059901","Delfshaven"), ("WK059902","Noord"),
    ("WK059903","Kralingen"), ("WK059904","Feijenoord"), ("WK059905","IJsselmonde"),
    ("WK059906","Prins Alexander"), ("WK059907","Charlois"), ("WK059908","Hoogvliet"),
]
records = []
for wijk_code, wijk_naam in wijken:
    records.append({
        "wijk_code": wijk_code,
        "wijk_naam": wijk_naam,
        "gemeente": "Rotterdam",
        "gemiddelde_woningwaarde": random.randint(200000, 600000),
        "gemiddeld_inkomen": random.randint(22000, 55000),
        "pct_eigenaar": round(random.uniform(20, 70), 1),
        "bevolkingsdichtheid": random.randint(500, 8000),
        "inwoners": random.randint(5000, 50000),
        "is_synthetic": True,
    })
with open("data/cbs_data.jsonl", "w") as f:
    for r in records:
        f.write(json.dumps(r) + "\n")
print(f"CBS: {len(records)} wijken zapisanych")

# WOZ - te same postcodes co BAG (jeden WOZ per BAG rekord)
woz_records = []
for i, bag_r in enumerate(records):  # records = lista BAG rekordow
    area = bag_r["oppervlakte"]
    woz_records.append({
        "woz_object_nummer": f"WOZ{i:08d}",
        "postcode": bag_r["postcode"],
        "huisnummer": bag_r["huisnummer"],
        "woz_waarde": int(area * random.randint(3000, 6000)),
        "peildatum": "2023-01-01",
        "gebruikscode": "1000",
        "is_synthetic": True,
    })
with open("data/woz_rotterdam.jsonl", "w") as f:
    for r in woz_records:
        f.write(json.dumps(r) + "\n")
print(f"WOZ: {len(woz_records)} rekordow zapisanych")

print("Wszystkie pliki gotowe w data/")