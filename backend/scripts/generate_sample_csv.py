"""Generate a 150-row sample camera import CSV matching the import template.

Deterministic; every row passes validate_camera_row.
Run: python scripts/generate_sample_csv.py [output_path]
"""

import csv
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

random.seed(1502026)

COLUMNS = [
    "camera_code", "name", "department_id", "site_id", "camera_type", "ownership",
    "public_facing", "vendor", "model", "ip_address", "latitude", "longitude",
    "district", "taluka", "address", "connectivity_status", "storage_type",
    "retention_days", "install_date", "amc_vendor", "amc_end_date",
    "maintenance_status", "status", "coverage_radius_m",
]

# district -> (taluka pool, lat range, lng range)
GEO = {
    "Ahmedabad": (["Ahmedabad City", "Daskroi"], (22.95, 23.10), (72.50, 72.68)),
    "Surat": (["Surat City", "Choryasi"], (21.12, 21.25), (72.78, 72.90)),
    "Vadodara": (["Vadodara City", "Waghodia"], (22.25, 22.38), (73.12, 73.24)),
    "Rajkot": (["Rajkot", "Kotda Sangani"], (22.25, 22.38), (70.74, 70.88)),
    "Kutch": (["Bhuj", "Anjar", "Mandvi"], (22.90, 23.35), (69.40, 69.90)),
    "Gandhinagar": (["Kalol", "Gandhinagar"], (23.15, 23.30), (72.40, 72.68)),
    "Valsad": (["Valsad", "Vapi"], (20.55, 20.75), (72.85, 73.05)),
    "Dahod": (["Dahod", "Jhalod"], (22.75, 22.90), (74.15, 74.35)),
    "Jamnagar": (["Jamnagar", "Kalavad"], (22.40, 22.55), (69.95, 70.15)),
    "Devbhumi Dwarka": (["Dwarka", "Khambhalia"], (22.15, 22.35), (68.85, 69.15)),
    "Patan": (["Patan", "Sidhpur"], (23.75, 23.95), (72.05, 72.45)),
    "Bhavnagar": (["Bhavnagar", "Mahuva"], (21.65, 21.85), (71.95, 72.25)),
    "Junagadh": (["Junagadh", "Keshod"], (21.45, 21.60), (70.40, 70.55)),
    "Mehsana": (["Mehsana", "Visnagar"], (23.55, 23.65), (72.30, 72.45)),
    "Surendranagar": (["Surendranagar", "Dhrangadhra"], (22.70, 22.80), (71.55, 71.85)),
}

DEPARTMENTS = ["POLICE", "HOME", "FCS", "RTO", "HEALTH", "MUNICIPAL", "GSRTC"]

VENDOR_MODELS = [
    ("Hikvision", "DS-2CD2T47G2-LU"), ("Hikvision", "DS-2DE4A425IW-DE"),
    ("Dahua", "DH-IPC-HDW5442T"), ("Dahua", "DH-SD49425XB-HNR"),
    ("CP Plus", "CP-USC-DA24L2"), ("CP Plus", "CP-UNC-DA41PL3"),
    ("Bosch", "FLEXIDOME 5100i"), ("Axis", "P3268-LV"),
    ("Honeywell", "HBW2PER1"), (" Panasonic".strip(), "WV-S25300L1"),
]

AMC_VENDORS = ["SecureTech AMC", "CitySafeguard Pvt Ltd", "V Guard Systems", "GujSec Services", "None"]
CAMERA_TYPES = ["FIXED", "FIXED", "FIXED", "DOME", "BULLET", "PTZ", "ANPR"]
CONN = ["ONLINE", "ONLINE", "ONLINE", "ONLINE", "OFFLINE", "UNKNOWN"]
MAINT = ["OK", "OK", "OK", "OK", "DUE", "FAULTY"]
STORAGE = ["CLOUD", "LOCAL", "NVR", "NONE"]


def days_ago(n):
    from datetime import date, timedelta
    return date.today() - timedelta(days=n)


def generate():
    rows = []
    seen = set()
    codes = iter(range(1, 10000))
    while len(rows) < 150:
        district = random.choice(list(GEO.keys()))
        taluka, (lat_lo, lat_hi), (lng_lo, lng_hi) = GEO[district]
        dept = random.choice(DEPARTMENTS)
        n = next(codes)
        code = f"CAM-{dept}-{n:04d}"
        if code in seen:
            continue
        seen.add(code)
        vendor, model = random.choice(VENDOR_MODELS)
        lat = round(random.uniform(lat_lo, lat_hi), 6)
        lng = round(random.uniform(lng_lo, lng_hi), 6)
        taluka_name = random.choice(taluka)
        install = days_ago(random.randint(120, 2600)).isoformat()
        amc_end = days_ago(random.randint(-730, 400)).isoformat()
        site_slug = f"{district.upper().replace(' ', '')[:6]}{n:04d}"
        rows.append({
            "camera_code": code,
            "name": f"{district} Cam {n:04d}",
            "department_id": dept,
            "site_id": "",  # optional column; left blank in generated sample
            "camera_type": random.choice(CAMERA_TYPES),
            "ownership": "PRIVATE" if random.random() < 0.06 else "GOVERNMENT",
            "public_facing": random.choice(["TRUE", "FALSE", "FALSE"]),
            "vendor": vendor,
            "model": model,
            "ip_address": f"10.{random.randint(0, 30)}.{random.randint(0, 255)}.{random.randint(2, 254)}",
            "latitude": lat,
            "longitude": lng,
            "district": district,
            "taluka": taluka_name,
            "address": f"Near {random.choice(['Cross Road', 'Chowkdi', 'Circuit House', 'Taluka Office', 'Market Yard'])}, {taluka_name}",
            "connectivity_status": random.choice(CONN),
            "storage_type": random.choice(STORAGE),
            "retention_days": random.choice([7, 15, 30]),
            "install_date": install,
            "amc_vendor": random.choice(AMC_VENDORS),
            "amc_end_date": amc_end,
            "maintenance_status": random.choice(MAINT),
            "status": "PENDING_VALIDATION" if random.random() < 0.04 else "ACTIVE",
            "coverage_radius_m": random.choice([80, 120, 150, 200, 300]),
        })
    return rows


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "..", "..", "docs", "sample_import_150.csv"
    )
    rows = generate()
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
