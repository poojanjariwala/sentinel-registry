"""Sentinel Camera Grid adapter: sync the real Gujarat Police camera set.

The grid publishes its camera set at cameras.json (the source of truth - the
set can change); each camera is an HLS playlist behind a password-gated origin.
sync_cameras_from_grid() is idempotent: it upserts Module-1 camera records and
HLS stream_sources for every catalogue entry, and disables (never deletes)
grid streams that disappear from the catalogue. Real URLs are never rewritten
by the SIM self-heal path.
"""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.camera import Camera
from app.models.department import Department
from app.models.module2 import StreamSource
from app.services import grid_client

GRID_DEPT_CODE = "POLICE"


def _district_from_name(name: str) -> str | None:
    """Best-effort district tag from the catalogue's free-text location name."""
    n = name.lower()
    for d in ["junagadh", "rajkot", "navsari", "gandhidham", "gir somnath", "ahmedabad", "gandhinagar", "surat", "vadodara", "patan", "valsad", "kachchh", "kutch"]:
        if d in n:
            return d.title()
    return None


def sync_cameras_from_grid(db: Session) -> dict:
    """Fetch the grid catalogue and upsert cameras + HLS stream sources."""
    if not grid_client.configured():
        return {"ok": False, "reason": "GRID_BASE_URL/GRID_EMAIL/GRID_PASSWORD not configured"}

    try:
        catalogue = _run(grid_client.fetch_camera_catalogue())
    except Exception as e:  # noqa: BLE001 - adapter boundary: report, don't crash
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}

    police = db.execute(select(Department).where(Department.code == GRID_DEPT_CODE)).scalar_one_or_none()
    if police is None:
        return {"ok": False, "reason": "POLICE department missing"}

    cameras = {
        c.camera_code: c
        for c in db.execute(select(Camera).where(Camera.camera_code.like("GP-%"))).scalars().all()
    }
    streams_by_code: dict[str, StreamSource] = {}
    for s in db.execute(select(StreamSource).where(StreamSource.vms_system == grid_client.GRID_VMS)).scalars().all():
        code = re.search(r"GP-(CAM\d+)", s.label) or re.search(r"GP-(CAM\d+)", s.source_url)
        if code:
            streams_by_code[code.group(1)] = s

    now = datetime.now(timezone.utc)
    created_c = updated_c = created_s = updated_s = 0
    seen: set[str] = set()

    for item in catalogue:
        grid_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not grid_id:
            continue
        seen.add(grid_id)
        code = f"GP-{grid_id.upper()}"          # GP-CAM01 .. GP-CAM30
        display = name or grid_id
        district = _district_from_name(display)

        cam = cameras.get(code)
        if cam is None:
            cam = Camera(camera_code=code, name=display, department_id=police.department_id, status="ACTIVE")
            db.add(cam)
            db.flush()
            cameras[code] = cam
            created_c += 1
        elif cam.name != display:
            cam.name = display
            updated_c += 1
        if district and not cam.district:
            cam.district = district
        cam.last_seen_at = now

        stream = streams_by_code.get(grid_id.upper())
        url = grid_client.camera_hls_url(grid_id)
        label = f"{display} · GP Grid"
        if stream is None:
            stream = StreamSource(
                camera_id=cam.camera_id,
                label=label,
                protocol="HLS",
                source_url=url,
                vms_system=grid_client.GRID_VMS,
                department_id=police.department_id,
                is_live=True,
                enabled=True,
                status="UNKNOWN",
                last_probe_at=None,
                analytics_enabled=False,
            )
            db.add(stream)
            streams_by_code[grid_id.upper()] = stream
            created_s += 1
        else:
            if stream.source_url != url:
                stream.source_url = url  # catalogue is authoritative for grid feeds
                updated_s += 1
            stream.enabled = True
            stream.label = label
        stream.updated_at = now

    # Catalogue no longer lists it: disable, never delete (audit trail).
    disabled = 0
    for key, s in streams_by_code.items():
        if key.lower() not in {g.lower() for g in seen}:
            if s.enabled:
                s.enabled = False
                disabled += 1

    db.commit()
    return {
        "ok": True,
        "source": grid_client.base_url(),
        "catalogue_size": len(catalogue),
        "cameras_created": created_c,
        "cameras_updated": updated_c,
        "streams_created": created_s,
        "streams_updated": updated_s,
        "streams_disabled": disabled,
    }


def _run(coro):
    """Bridge for sync callers (admin routes run in worker threads, no loop)."""
    import asyncio

    return asyncio.run(coro)
