"""Sentinel Camera Grid adapter: sync the real Gujarat Police camera set.

The grid publishes its camera set at cameras.json (the source of truth - the
set can change); each camera is an HLS playlist behind a password-gated origin
and an RTSP endpoint on the public IP (the sanctioned AI-inference path).
sync_cameras_from_grid() is idempotent: it upserts Module-1 camera records, a
HLS (viewing) stream source for every catalogue entry, and - when
GRID_RTSP_HOST is configured - a REDACTED-credential RTSP stream row marked
analytics_enabled=True for the grid-rtsp engine. Disappearing catalogue
entries disable (never delete) streams. Real URLs are never rewritten by the
SIM self-heal path.
"""

import re
from datetime import datetime, timezone
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.camera import Camera
from app.models.department import Department
from app.models.module2 import StreamSource
from app.services import grid_client

GRID_DEPT_CODE = "POLICE"


def redacted_rtsp_url(grid_id: str) -> str:
    """Credential-free RTSP url persisted in the DB (rtsp_client injects the
    real credentials at read time, from grid settings)."""
    from app.core.config import get_settings

    s = get_settings()
    email = quote((s.grid_email or "").strip(), safe="")
    host = (s.grid_rtsp_host or "").strip()
    return f"rtsp://{email}:***@{host}:{s.grid_rtsp_port}/stream/{grid_id}"


def _district_from_name(name: str) -> str | None:
    """Best-effort district tag from the catalogue's free-text location name."""
    n = name.lower()
    for d in ["junagadh", "rajkot", "navsari", "gandhidham", "gir somnath", "ahmedabad", "gandhinagar", "surat", "vadodara", "patan", "valsad", "kachchh", "kutch"]:
        if d in n:
            return d.title()
    return None


def _grid_id_from_url(url: str) -> str:
    """Camera grid id from a stream URL: RTSP /stream/<id> or grid-HLS
    /<id>/... path segment. '' when the URL is not recognisably a grid url
    (e.g. the redacted-credential RTSP rows still match via /stream/)."""
    if not url:
        return ""
    m = re.search(r"/stream/([^/?]+)", url)
    if m:
        return m.group(1).strip()
    base = grid_client.base_url()
    if base and url.startswith(base + "/"):
        seg = url[len(base) + 1:].split("/", 1)[0].strip()
        if seg.lower().startswith("cam") or seg.lower().endswith(".m3u8"):
            return re.sub(r"\.m3u8$", "", seg, flags=re.IGNORECASE)
    return ""


def sync_cameras_from_grid(db: Session) -> dict:
    """Fetch the grid catalogue and upsert cameras + HLS/RTSP stream sources."""
    if not grid_client.configured():
        return {"ok": False, "reason": "GRID_BASE_URL/GRID_EMAIL/GRID_PASSWORD not configured"}

    try:
        # Isolated client/loop: this runs via asyncio.run in a worker thread
        # while the shared client is bound to the app's event loop (same
        # reason federation uses the isolated fetch).
        catalogue = _run(grid_client.fetch_camera_catalogue_isolated())
    except Exception as e:  # noqa: BLE001 - adapter boundary: report, don't crash
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}

    police = db.execute(select(Department).where(Department.code == GRID_DEPT_CODE)).scalar_one_or_none()
    if police is None:
        return {"ok": False, "reason": "POLICE department missing"}

    cameras = {
        c.camera_code: c
        for c in db.execute(select(Camera).where(Camera.camera_code.like("GP-%"))).scalars().all()
    }
    # Keyed "H:<GRIDID>" (HLS viewing) / "R:<GRIDID>" (RTSP inference).
    # Keyed from the source URL first (HLS path segment or RTSP /stream/<id>),
    # falling back to the GP-CAMxx label marker for legacy rows. Duplicates
    # from earlier keying bugs are healed: one row per (protocol, camera) is
    # kept, the rest are disabled (never deleted - audit trail).
    streams_by_code: dict[str, StreamSource] = {}
    healed = 0
    for s in db.execute(select(StreamSource).where(StreamSource.vms_system == grid_client.GRID_VMS)).scalars().all():
        gid = _grid_id_from_url(s.source_url)
        if not gid:
            m = re.search(r"GP-(CAM\d+)", s.label or "")
            gid = m.group(1) if m else ""
        if not gid:
            continue
        key = ("R:" if s.protocol == "RTSP" else "H:") + gid.upper()
        prev = streams_by_code.get(key)
        if prev is None:
            streams_by_code[key] = s
        else:
            keep, drop = (s, prev) if (s.enabled and not prev.enabled) else (prev, s)
            streams_by_code[key] = keep
            if drop.enabled:
                drop.enabled = False
                healed += 1

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

        # --- HLS (viewing) stream row, as before -----------------------
        stream = streams_by_code.get("H:" + grid_id.upper())
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
            streams_by_code["H:" + grid_id.upper()] = stream
            created_s += 1
        else:
            if stream.source_url != url:
                stream.source_url = url  # catalogue is authoritative for grid feeds
                updated_s += 1
            stream.enabled = True
            stream.label = label
        stream.updated_at = now

        # --- RTSP (inference) stream row: opt-in via GRID_RTSP_HOST -----
        # analytics_enabled=True marks it for the grid-rtsp engine; creds
        # stay redacted in the DB and are injected from settings at read.
        if grid_client.rtsp_configured():
            rurl = redacted_rtsp_url(grid_id)
            rst = streams_by_code.get("R:" + grid_id.upper())
            if rst is None:
                rst = StreamSource(
                    camera_id=cam.camera_id,
                    label=f"{display} · GP Grid RTSP",
                    protocol="RTSP",
                    source_url=rurl,
                    vms_system=grid_client.GRID_VMS,
                    department_id=police.department_id,
                    is_live=True,
                    enabled=True,
                    status="UNKNOWN",
                    last_probe_at=None,
                    analytics_enabled=True,
                )
                db.add(rst)
                streams_by_code["R:" + grid_id.upper()] = rst
                created_s += 1
            else:
                rst.enabled = True
                rst.label = f"{display} · GP Grid RTSP"
                rst.updated_at = now
                updated_s += 1
        else:
            rst = streams_by_code.get("R:" + grid_id.upper())
            if rst is not None and rst.enabled:
                rst.enabled = False  # RTSP inference switched off in config
                updated_s += 1

    # Catalogue no longer lists it: disable, never delete (audit trail).
    seen_lower = {g.lower() for g in seen}
    disabled = 0
    for key, s in streams_by_code.items():
        if key.split(":", 1)[1].lower() not in seen_lower:
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
        "duplicates_healed": healed,
    }


def _run(coro):
    """Bridge for sync callers (admin routes run in worker threads, no loop)."""
    import asyncio

    return asyncio.run(coro)
