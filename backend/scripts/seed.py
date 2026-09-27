"""Seed the Sentinel Registry database with demo data.

Idempotent: skips existing rows. Run: python scripts/seed.py
"""

import csv
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func, select

from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models import Base
from app.models.camera import Camera
from app.models.department import Department, Site
from app.models.gap_run import GapAnalysisRun
from app.models.user import Role, User, UserRole
from app.services.sentinel_adapter import seed_edge_streams, seed_watchlist
try:
    from scripts.seed_data import (
        AMC_VENDORS, CONNECTIVITY_MIX, DEMO_PASSWORD, DEPARTMENTS, DISTRICT_WEIGHT,
        MAINTENANCE_MIX, SITES, STORAGE_MIX, TYPE_MIX, VENDORS, days_ago, pick_weighted,
    )
except ImportError:  # running as a plain script: python scripts/seed.py
    from seed_data import (
        AMC_VENDORS, CONNECTIVITY_MIX, DEMO_PASSWORD, DEPARTMENTS, DISTRICT_WEIGHT,
        MAINTENANCE_MIX, SITES, STORAGE_MIX, TYPE_MIX, VENDORS, days_ago, pick_weighted,
    )


def camera_code(site_name: str, site_no: int, idx: int) -> str:
    slug = "".join(ch for ch in site_name.upper() if ch.isalnum())[:6]
    return f"CAM-{slug}{site_no:02d}-{idx:03d}"


def generate_camera_rows():
    rows = []
    for site_no, (dept_code, site_name, district, taluka, lat, lng) in enumerate(SITES, start=1):
        base = DISTRICT_WEIGHT.get(district, 2)
        count = max(6, min(40, base * random.randint(3, 6)))
        for i in range(1, count + 1):
            jitter_lat = random.uniform(-0.03, 0.03)
            jitter_lng = random.uniform(-0.03, 0.03)
            vendor, model = random.choice(VENDORS)
            rows.append({
                "camera_code": camera_code(site_name, site_no, i),
                "name": f"{site_name} Cam {i:02d}",
                "site_name": site_name,
                "camera_type": pick_weighted(TYPE_MIX),
                "vendor": vendor,
                "model": model,
                "latitude": round(lat + jitter_lat, 6),
                "longitude": round(lng + jitter_lng, 6),
                "connectivity_status": pick_weighted(CONNECTIVITY_MIX),
                "maintenance_status": pick_weighted(MAINTENANCE_MIX),
                "storage_type": pick_weighted(STORAGE_MIX),
                "retention_days": random.choice([7, 15, 30]),
                "install_date": days_ago(random.randint(120, 2600)),
                "amc_end_date": days_ago(random.randint(-730, 400)),
            })
    return rows


def seed_reference(db):
    for name, desc in [
        ("STATE_ADMIN", "Full state-wide administration"),
        ("DEPARTMENT_ADMIN", "Department-scoped administration"),
        ("OPERATOR", "Department-scoped operator"),
        ("AUDITOR", "State-wide audit access"),
        ("VIEWER", "Read-only access"),
    ]:
        if not db.get(Role, name):
            db.add(Role(name=name, description=desc))
    db.flush()

    depts = {}
    for name, code, desc in DEPARTMENTS:
        d = db.execute(select(Department).where(Department.code == code)).scalar_one_or_none()
        if not d:
            d = Department(name=name, code=code, description=desc)
            db.add(d)
            db.flush()
        depts[code] = d
    db.commit()
    return depts


def seed_sites(db, depts):
    sites = {}
    for dept_code, name, district, taluka, lat, lng in SITES:
        s = db.execute(select(Site).where(Site.name == name)).scalar_one_or_none()
        if not s:
            s = Site(
                department_id=depts[dept_code].department_id,
                name=name, district=district, taluka=taluka,
                latitude=lat, longitude=lng,
            )
            db.add(s)
            db.flush()
        sites[name] = s
    db.commit()
    return sites


def seed_users(db, depts):
    demo = [
        ("State Admin", "state.admin@sentinel.local", "STATE_ADMIN", None),
        ("Police Operator", "police.op@sentinel.local", "OPERATOR", "POLICE"),
        ("Municipal Operator", "muni.op@sentinel.local", "OPERATOR", "MUNICIPAL"),
        ("State Auditor", "auditor@sentinel.local", "AUDITOR", None),
        ("Dept Admin", "dept.admin@sentinel.local", "DEPARTMENT_ADMIN", "POLICE"),
    ]
    for name, email, role, dept_code in demo:
        if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
            continue
        u = User(
            name=name, email=email,
            password_hash=hash_password(DEMO_PASSWORD),
            department_id=depts[dept_code].department_id if dept_code else None,
            status="ACTIVE",
        )
        db.add(u)
        db.flush()
        db.add(UserRole(
            user_id=u.user_id, role_name=role,
            department_id=depts[dept_code].department_id if dept_code else None,
        ))
    db.commit()


def seed_cameras(db, sites, rows):
    created = 0
    for r in rows:
        exists = db.execute(
            select(Camera).where(Camera.camera_code == r["camera_code"])
        ).scalar_one_or_none()
        if exists:
            continue
        site = sites[r["site_name"]]
        db.add(Camera(
            camera_code=r["camera_code"],
            name=r["name"],
            department_id=site.department_id,
            site_id=site.site_id,
            camera_type=r["camera_type"],
            ownership="GOVERNMENT" if random.random() > 0.05 else "PRIVATE",
            public_facing=random.random() > 0.3,
            vendor=r["vendor"],
            model=r["model"],
            ip_address=f"10.{random.randint(0, 30)}.{random.randint(0, 255)}.{random.randint(2, 254)}",
            latitude=r["latitude"],
            longitude=r["longitude"],
            location=f"SRID=4326;POINT({r['longitude']} {r['latitude']})",
            district=site.district,
            taluka=site.taluka,
            address=f"Near {site.name}",
            connectivity_status=r["connectivity_status"],
            storage_type=r["storage_type"],
            retention_days=r["retention_days"],
            install_date=r["install_date"],
            amc_vendor=random.choice(AMC_VENDORS),
            amc_end_date=r["amc_end_date"],
            maintenance_status=r["maintenance_status"],
            status="ACTIVE" if random.random() > 0.03 else "PENDING_VALIDATION",
            coverage_radius_m=random.choice([80, 120, 150, 200, 300]),
        ))
        created += 1
    db.commit()
    return created


def seed_gap_run(db, user_id):
    if db.execute(select(GapAnalysisRun).limit(1)).scalar_one_or_none():
        return
    run = GapAnalysisRun(
        created_by=user_id,
        params_json={"departments": [], "districts": [], "resolution": 8,
                     "min_cameras_per_cell": 1, "ageing_years": 5.0},
        summary_json={
            "generated_at": None,
            "params": {"departments": [], "districts": [], "resolution": 8,
                       "min_cameras_per_cell": 1, "ageing_years": 5.0},
            "total_cameras": 0, "hex_covered": 0, "hex_thin": 0,
            "ageing_count": 0, "amc_expired_count": 0,
            "by_district": [], "ageing_sample": [], "cells": [],
            "note": "Placeholder seeded run - run a live analysis from the UI for real numbers",
        },
        camera_count_total=0,
        uncovered_hex_count=0,
    )
    db.add(run)
    db.commit()


def write_demo_import_csv(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = csv.writer(open(path, "w", encoding="utf-8", newline=""))
    buf.writerow([
        "camera_code", "name", "department_id", "latitude", "longitude", "district",
        "camera_type", "vendor", "connectivity_status", "storage_type",
        "retention_days", "install_date", "amc_vendor", "amc_end_date",
        "maintenance_status", "status",
    ])
    buf.writerow(["CAM-DEMO-001", "Demo Entry Road Cam", "POLICE", "23.0225", "72.5714",
                  "Ahmedabad", "FIXED", "Hikvision", "ONLINE", "NVR", "30",
                  "2023-04-12", "SecureTech AMC", "2027-03-31", "OK", "ACTIVE"])
    buf.writerow(["CAM-DEMO-002", "Demo Chowk Bazaar Cam", "MUNICIPAL", "21.1950", "72.8300",
                  "Surat", "DOME", "Dahua", "OFFLINE", "LOCAL", "15",
                  "2021-08-02", "CitySafeguard Pvt Ltd", "2026-01-15", "FAULTY", "ACTIVE"])
    # intentionally invalid rows for dry-run demo:
    buf.writerow(["CAM-DEMO-003", "", "RTO", "23.0000", "99.0000",
                  "Rajkot", "BULLET", "CP Plus", "ONLINE", "NVR", "15",
                  "2024-01-15", "None", "2026-12-31", "OK", "ACTIVE"])
    buf.writerow(["CAM-DEMO-004", "Duplicate code row", "RTO", "22.3039", "70.8022",
                  "Rajkot", "BULLET", "Axis", "ONLINE", "CLOUD", "30",
                  "2025-05-10", "None", "2026-12-31", "OK", "ACTIVE"])
    buf.writerow(["CAM-DEMO-004", "Duplicate code row 2", "RTO", "22.3050", "70.8030",
                  "Rajkot", "BULLET", "Axis", "ONLINE", "CLOUD", "30",
                  "2025-05-10", "None", "2026-12-31", "OK", "ACTIVE"])
    buf.writerow(["CAM-FOREIGN-005", "Out-of-scope dept row", "HEALTH", "22.3039", "70.8022",
                  "Rajkot", "BULLET", "Axis", "ONLINE", "CLOUD", "30",
                  "2025-05-10", "None", "2026-12-31", "OK", "ACTIVE"])


def main():
    force = os.environ.get("FORCE_SEED") == "1"
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        depts = seed_reference(db)
        sites = seed_sites(db, depts)
        seed_users(db, depts)
        created = seed_cameras(db, sites, generate_camera_rows())
        write_demo_import_csv(os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "docs", "demo_import.csv")
        ))
        admin = db.execute(
            select(User).where(User.email == "state.admin@sentinel.local")
        ).scalar_one()
        seed_gap_run(db, admin.user_id)
        n_watch = seed_watchlist(db, admin.user_id)
        edge = seed_edge_streams(db)
        print(f"Watchlist: {n_watch} seeded entries · Edge ANPR: +{edge['created']} streams (EDGE-DEMO)")
        total = db.scalar(select(func.count()).select_from(Camera))
        print(f"Seed complete: {len(depts)} departments, {len(sites)} sites, {created} new cameras ({total} total)")
        print("Demo users (development only):")
        for email in ("state.admin@sentinel.local", "police.op@sentinel.local",
                      "muni.op@sentinel.local", "auditor@sentinel.local",
                      "dept.admin@sentinel.local"):
            print(f"  {email} / {DEMO_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
