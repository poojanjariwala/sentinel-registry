"""Static demo data for seeding (Gujarat-flavored, deterministic)."""

import random
from datetime import date, timedelta

random.seed(20260925)

DEMO_PASSWORD = "Sentinel@2026"

DEPARTMENTS = [
    ("Police Department", "POLICE", "Law and order, traffic and crime policing"),
    ("Home Department", "HOME", "Public domain cameras for traffic and law & order"),
    ("Food & Civil Supplies", "FCS", "Godowns, PDS shops and ration logistics"),
    ("RTO / Transport", "RTO", "Offices, testing tracks and checkpoints"),
    ("Health Department", "HEALTH", "Hospitals, PHCs and medical colleges"),
    ("Municipal Corporations", "MUNICIPAL", "City surveillance and SWM monitoring"),
    ("GSRTC", "GSRTC", "Bus stations, depots and terminals"),
]

# (dept_code, name, district, taluka, lat, lng)
SITES = [
    ("POLICE", "Police Bhavan Ahmedabad", "Ahmedabad", "Ahmedabad City", 23.0225, 72.5714),
    ("POLICE", "Kalol Police Station", "Gandhinagar", "Kalol", 23.2457, 72.4979),
    ("POLICE", "Surat City Police HQ", "Surat", "Surat City", 21.1702, 72.8311),
    ("POLICE", "Vadodara Crime Branch", "Vadodara", "Vadodara City", 22.3072, 73.1812),
    ("POLICE", "Rajkot Rural Police Line", "Rajkot", "Rajkot", 22.3039, 70.8022),
    ("POLICE", "Bhuj Police Station", "Kutch", "Bhuj", 23.2419, 69.6669),
    ("POLICE", "Valsad Town Police Station", "Valsad", "Valsad", 20.6075, 72.9345),
    ("POLICE", "Dahod SP Office", "Dahod", "Dahod", 22.8385, 74.2544),
    ("POLICE", "Jamnagar Police HQ", "Jamnagar", "Jamnagar", 22.4707, 70.0577),
    ("POLICE", "Dwarka Coastal Police Station", "Devbhumi Dwarka", "Dwarka", 22.2394, 68.9678),
    ("HOME", "Home Dept Traffic Cell Ahmedabad", "Ahmedabad", "Ahmedabad City", 23.0323, 72.5266),
    ("HOME", "Home Dept Traffic Cell Surat", "Surat", "Surat City", 21.1959, 72.8302),
    ("FCS", "Central Godown Kalol", "Gandhinagar", "Kalol", 23.2470, 72.4950),
    ("FCS", "PDS Warehouse Surat", "Surat", "Choryasi", 21.1458, 72.8394),
    ("RTO", "RTO Ahmedabad Sub-division", "Ahmedabad", "Ahmedabad City", 23.0276, 72.5813),
    ("RTO", "RTO Surat Check Post", "Surat", "Surat City", 21.2049, 72.8403),
    ("RTO", "RTO Vadodara Testing Track", "Vadodara", "Vadodara City", 22.3196, 73.1830),
    ("HEALTH", "New Civil Hospital Ahmedabad", "Ahmedabad", "Ahmedabad City", 23.0089, 72.5954),
    ("HEALTH", "Surat Municipal Hospital", "Surat", "Surat City", 21.1933, 72.8354),
    ("HEALTH", "Rajkot Civil Hospital", "Rajkot", "Rajkot", 22.2994, 70.7987),
    ("HEALTH", "Dahod PHC Cluster", "Dahod", "Dahod", 22.8470, 74.2540),
    ("MUNICIPAL", "AMC West Zone Office", "Ahmedabad", "Ahmedabad City", 23.0389, 72.5101),
    ("MUNICIPAL", "SMC Zone-4 Office", "Surat", "Surat City", 21.1702, 72.8455),
    ("MUNICIPAL", "VMC Ward-12 Office", "Vadodara", "Vadodara City", 22.2990, 73.2010),
    ("MUNICIPAL", "RMC Ward-7 Office", "Rajkot", "Rajkot", 22.3100, 70.7990),
    ("GSRTC", "Geeta Mandir Bus Station", "Ahmedabad", "Ahmedabad City", 23.0195, 72.5702),
    ("GSRTC", "Surat Adajan Depot", "Surat", "Adajan", 21.2100, 72.8000),
    ("GSRTC", "Central Bus Terminal Vadodara", "Vadodara", "Vadodara City", 22.2990, 73.1900),
    ("GSRTC", "Rajkot Bus Station", "Rajkot", "Rajkot", 22.3030, 70.8040),
    ("GSRTC", "Bhuj Depot", "Kutch", "Bhuj", 23.2480, 69.6700),
]

VENDORS = [
    ("Hikvision", "DS-2CD2T47G2-LU"),
    ("Hikvision", "DS-2DE4A425IW-DE"),
    ("Dahua", "DH-IPC-HDW5442T"),
    ("Dahua", "DH-SD49425XB-HNR"),
    ("CP Plus", "CP-USC-DA24L2"),
    ("CP Plus", "CP-UNC-DA41PL3"),
    ("Bosch", "FLEXIDOME 5100i"),
    ("Axis", "P3268-LV"),
]

CONNECTIVITY_MIX = [("ONLINE", 0.78), ("OFFLINE", 0.12), ("UNKNOWN", 0.10)]
MAINTENANCE_MIX = [("OK", 0.82), ("DUE", 0.11), ("FAULTY", 0.07)]
STORAGE_MIX = [("CLOUD", 0.25), ("LOCAL", 0.40), ("NVR", 0.30), ("NONE", 0.05)]
TYPE_MIX = [("FIXED", 0.55), ("DOME", 0.20), ("BULLET", 0.15), ("PTZ", 0.07), ("ANPR", 0.03)]
AMC_VENDORS = ["SecureTech AMC", "CitySafeguard Pvt Ltd", "V Guard Systems", "GujSec Services"]

# relative camera count weight per district
DISTRICT_WEIGHT = {
    "Ahmedabad": 6, "Surat": 5, "Vadodara": 4, "Rajkot": 3, "Kutch": 2,
    "Gandhinagar": 2, "Valsad": 1, "Dahod": 1, "Jamnagar": 1, "Devbhumi Dwarka": 1,
}


def pick_weighted(pairs):
    r = random.random()
    acc = 0.0
    for val, w in pairs:
        acc += w
        if r <= acc:
            return val
    return pairs[-1][0]


def days_ago(n: int) -> date:
    return date.today() - timedelta(days=n)
