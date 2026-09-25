"""Gap analysis service: H3 hex coverage, uncovered zones, ageing infrastructure."""

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.camera import Camera
from app.models.user import Role, UserRole

try:
    import h3
except ImportError:  # pragma: no cover
    h3 = None

AGEING_DEFAULT_YEARS = 5.0


def _scope_filter(user, db: Session):
    role_names = db.execute(
        select(Role.name).join(UserRole, UserRole.role_name == Role.name).where(UserRole.user_id == user.user_id)
    ).scalars().all()
    if any(r in {"STATE_ADMIN", "AUDITOR"} for r in role_names):
        return None
    dept_ids = [
        row[0]
        for row in db.execute(select(UserRole.department_id).where(UserRole.user_id == user.user_id)).all()
        if row[0]
    ]
    return Camera.department_id.in_(dept_ids) if dept_ids else Camera.department_id.in_(["__none__"])


def _base_query(db: Session, user, departments, districts):
    stmt = select(Camera).where(
        Camera.status.in_(["ACTIVE", "PENDING_VALIDATION"]),
        Camera.latitude.is_not(None),
        Camera.longitude.is_not(None),
    )
    flt = _scope_filter(user, db)
    if flt is not None:
        stmt = stmt.where(flt)
    if departments:
        stmt = stmt.where(Camera.department_id.in_(departments))
    if districts:
        stmt = stmt.where(func.lower(Camera.district).in_([d.lower() for d in districts]))
    return stmt


def run_gap_analysis(
    db: Session,
    user,
    departments: list[str] | None = None,
    districts: list[str] | None = None,
    resolution: int = 8,
    min_cameras_per_cell: int = 1,
    ageing_years: float = AGEING_DEFAULT_YEARS,
) -> dict:
    """Compute H3 hex coverage plus ageing/AMC summary. Returns the summary dict."""
    if h3 is None:
        raise RuntimeError("h3 library unavailable")

    stmt = _base_query(db, user, departments, districts)
    cameras = db.execute(stmt).scalars().all()

    # --- Hex coverage -------------------------------------------------------
    cell_counts: dict[str, int] = {}
    for cam in cameras:
        try:
            cell = h3.latlng_to_cell(cam.latitude, cam.longitude, resolution)
        except (ValueError, TypeError):
            continue
        cell_counts[cell] = cell_counts.get(cell, 0) + 1

    covered = sum(1 for c in cell_counts.values() if c >= min_cameras_per_cell)
    thin = sum(1 for c in cell_counts.values() if 0 < c < min_cameras_per_cell)
    top_uncovered = [
        {"cell_id": c, "camera_count": n, "classification": "COVERED" if n >= min_cameras_per_cell else "THIN"}
        for c, n in sorted(cell_counts.items(), key=lambda kv: -kv[1])[:50]
    ]

    # --- District breakdown --------------------------------------------------
    by_district_map: dict[str, dict] = {}
    for cam in cameras:
        d = (cam.district or "UNKNOWN").title()
        entry = by_district_map.setdefault(d, {"district": d, "cameras": 0, "offline": 0, "faulty": 0, "ageing": 0, "amc_expired": 0})
        entry["cameras"] += 1
        if cam.connectivity_status == "OFFLINE":
            entry["offline"] += 1
        if cam.maintenance_status == "FAULTY":
            entry["faulty"] += 1

    # --- Ageing + AMC --------------------------------------------------------
    today = date.today()
    ageing_cutoff = today.replace(year=today.year - int(ageing_years))
    ageing_rows = []
    amc_expired_count = 0
    for cam in cameras:
        ageing = cam.install_date is not None and cam.install_date <= ageing_cutoff
        amc_expired = cam.amc_end_date is not None and cam.amc_end_date < today
        if amc_expired:
            amc_expired_count += 1
        if ageing:
            d = (cam.district or "UNKNOWN").title()
            by_district_map.setdefault(d, {"district": d, "cameras": 0, "offline": 0, "faulty": 0, "ageing": 0, "amc_expired": 0})
            by_district_map[d]["ageing"] += 1
            if len(ageing_rows) < 200:
                ageing_rows.append({
                    "camera_id": cam.camera_id,
                    "camera_code": cam.camera_code,
                    "name": cam.name,
                    "district": cam.district,
                    "install_date": cam.install_date.isoformat(),
                    "amc_end_date": cam.amc_end_date.isoformat() if cam.amc_end_date else None,
                    "maintenance_status": cam.maintenance_status,
                    "ageing": True,
                    "amc_expired": amc_expired,
                })

    total = len(cameras)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params": {
            "departments": departments or [],
            "districts": districts or [],
            "resolution": resolution,
            "min_cameras_per_cell": min_cameras_per_cell,
            "ageing_years": ageing_years,
        },
        "total_cameras": total,
        "hex_covered": covered,
        "hex_thin": thin,
        "cells": [
            {"cell_id": c, "camera_count": n, "classification": "COVERED" if n >= min_cameras_per_cell else "THIN"}
            for c, n in cell_counts.items()
        ],
        "by_district": sorted(by_district_map.values(), key=lambda e: -e["cameras"]),
        "ageing_sample": ageing_rows,
        "ageing_count": sum(e["ageing"] for e in by_district_map.values()),
        "amc_expired_count": amc_expired_count,
    }
    return summary
