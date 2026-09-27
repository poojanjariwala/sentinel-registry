"""Module 3: VMS federation & middleware.

Adapter framework per PRD §12-13 / TRD 5.3 + ARCH-007: every departmental VMS
is reached through an adapter that translates vendor specifics into the common
internal model (discover / health), and declares its capabilities explicitly.

Design rules:
- Federation over replacement (PRD §8.3): adapters wrap existing VMS, they
  never require migrating cameras into a central VMS.
- Failure isolation (AC-11 / NFR-001): an adapter error is captured per-VMS
  and reported - it can never crash the sync loop or the platform.
- Capabilities are declared (TRD §13): getCameras/getCameraStatus/getStream/
  getHealth are the common set; PTZ/export etc. stay optional and absent here.
- Secrets (SEC-004/SEC-010): the registry stores only env-var NAMES; values
  are resolved from the environment at call time and never persisted.
"""

import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.camera import Camera
from app.models.department import Department
from app.models.federation import VmsSystem
from app.models.module2 import StreamSource
from app.services import grid_client
from app.services.grid_sync import _district_from_name, _run

CORE_CAPABILITIES = ["LIVE_STREAM", "CAMERA_STATUS", "EVENTS", "RECORDING_SEARCH"]


class AdapterError(Exception):
    """Raised by adapters; captured per-VMS by the sync loop (AC-11)."""


# ---------------------------------------------------------------------------
# Adapters (TRD §13: each translates vendor specifics into the common model)
# ---------------------------------------------------------------------------


def _grid_discover(registry_row: VmsSystem) -> list[dict]:
    """Sentinel Camera Grid adapter: catalogue at /cameras.json.

    Uses an isolated client/loop (adapter runs via asyncio.run in worker
    threads; the shared in-process client is bound to the app's loop).
    """
    if not grid_client.configured():
        raise AdapterError("GRID_BASE_URL/GRID_EMAIL/GRID_PASSWORD not configured")
    catalogue = _run(grid_client.fetch_camera_catalogue_isolated())
    out = []
    for item in catalogue:
        gid = str(item.get("id") or "").strip()
        if not gid:
            continue
        name = str(item.get("name") or "").strip() or gid
        out.append({
            "external_ref": f"GP-{gid.upper()}",
            "name": name,
            "district": _district_from_name(name),
            "protocol": "HLS",
            "source_url": grid_client.camera_hls_url(gid),
            "vms_system": grid_client.GRID_VMS,
        })
    return out


def _grid_health(registry_row: VmsSystem) -> dict:
    """Health = can we still fetch the catalogue (session + origin alive)."""
    cams = _grid_discover(registry_row)
    return {"reachable": True, "camera_count": len(cams)}


def _generic_hls_discover(registry_row: VmsSystem) -> list[dict]:
    """Generic HLS VMS adapter: fetches a JSON manifest of cameras.

    Contract: GET {base_url} -> {"cameras": [{"id","name","url", ...}]}.
    Non-200 or malformed manifests raise AdapterError (reported, not fatal).
    """
    import httpx

    base = (registry_row.base_url or "").strip()
    if not base:
        raise AdapterError("VMS base_url not configured")
    try:
        resp = httpx.get(base, timeout=10.0, follow_redirects=True,
                         headers={"User-Agent": "SentinelRegistry/1.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001 - adapter boundary
        raise AdapterError(f"{type(e).__name__}: {e}") from e
    items = data.get("cameras") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise AdapterError("manifest is not a camera list")
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id") or not item.get("url"):
            continue
        name = str(item.get("name") or item["id"])
        out.append({
            "external_ref": str(item["id"]),
            "name": name,
            "district": item.get("district"),
            "protocol": "HLS",
            "source_url": str(item["url"]),
            "vms_system": registry_row.name,
        })
    return out


def _generic_hls_health(registry_row: VmsSystem) -> dict:
    cams = _generic_hls_discover(registry_row)
    return {"reachable": True, "camera_count": len(cams)}


def _mock_discover(registry_row: VmsSystem) -> list[dict]:
    """Mock vendor adapter (PRD §46): deterministic demo cameras, no network."""
    base = (registry_row.base_url or "").rstrip("/") or "http://web/hls"
    out = []
    for i in range(1, 5):
        out.append({
            "external_ref": f"{registry_row.name}-CAM{i:02d}",
            "name": f"Demo scene {i:02d} ({registry_row.vendor})",
            "district": None,
            "protocol": "HLS",
            "source_url": f"{base}/cam{i}/index.m3u8",
            "vms_system": registry_row.name,
        })
    return out


def _mock_health(registry_row: VmsSystem) -> dict:
    return {"reachable": True, "camera_count": 4}


_ADAPTERS: dict[str, tuple[object, object]] = {
    "grid": (_grid_discover, _grid_health),
    "generic_hls": (_generic_hls_discover, _generic_hls_health),
    "mock": (_mock_discover, _mock_health),
}


def adapter_kinds() -> list[str]:
    return sorted(_ADAPTERS)


# ---------------------------------------------------------------------------
# Registry + sync
# ---------------------------------------------------------------------------


def ensure_default_registrations(db: Session) -> None:
    """Idempotently register the known departmental VMS ecosystems.

    The real grid is registered from env config; a mock vendor (PRD §46
    "mock vendor adapter") is registered DISABLED so the live wall keeps
    showing only the 30 real cameras - enabling it in the Federation UI is
    a one-click demo of multi-VMS integration (AC-01). Existing rows are
    never overwritten.
    """
    if db.scalar(select(VmsSystem).where(VmsSystem.name == grid_client.GRID_VMS)) is None:
        db.add(VmsSystem(
            name=grid_client.GRID_VMS,
            vendor="Sentinel Grid (corp8)",
            adapter_kind="grid",
            base_url=grid_client.base_url() or None,
            auth_env_keys=["GRID_EMAIL", "GRID_PASSWORD"],
            capabilities=CORE_CAPABILITIES,
        ))
    if db.scalar(select(VmsSystem).where(VmsSystem.name == "MOCK-VENDOR-A")) is None:
        db.add(VmsSystem(
            name="MOCK-VENDOR-A",
            vendor="Mock VMS Vendor A",
            adapter_kind="mock",
            base_url="http://web/hls",
            auth_env_keys=[],
            capabilities=["LIVE_STREAM", "CAMERA_STATUS"],
            enabled=False,  # demo adapter: enable from the Federation UI
        ))
    db.commit()


def resolve_auth_env(names: list | None) -> dict[str, str]:
    """Resolve env-var NAMES to values at call time (values never stored)."""
    out: dict[str, str] = {}
    for n in names or []:
        v = os.environ.get(str(n))
        if v:
            out[str(n)] = v
    return out


def discover_vms(db: Session, vms: VmsSystem) -> dict:
    """Run one adapter's discovery + upsert cameras/streams (failure-isolated).

    Idempotent like grid_sync: upsert by external_ref, enable what the source
    still lists, disable (never delete) what it drops. Extra source cameras
    (e.g. simulated feeds) are left untouched.
    """
    discover, _health_fn = _ADAPTERS.get(vms.adapter_kind, (None, None))
    now = datetime.now(timezone.utc)
    if discover is None:
        return {"vms": vms.name, "ok": False, "reason": f"unknown adapter {vms.adapter_kind!r}"}
    try:
        cams = discover(vms)
    except Exception as e:  # noqa: BLE001 - AC-11: report, never crash
        vms.status = "OFFLINE"
        vms.last_error = f"{type(e).__name__}: {e}"
        db.commit()
        return {"vms": vms.name, "ok": False, "reason": vms.last_error}
    if not cams:
        # An empty catalogue is a FAILED discovery, not a decision: treating
        # it as authoritative would disable every stream of this VMS (this
        # exact foot-gun wiped GP-GRID once during a grid cooldown).
        vms.status = "OFFLINE"
        vms.last_error = "discovery returned an empty catalogue; streams left untouched"
        db.commit()
        return {"vms": vms.name, "ok": False, "reason": vms.last_error}

    dept = db.scalar(select(Department).where(Department.code == "POLICE"))
    if dept is None:
        return {"vms": vms.name, "ok": False, "reason": "POLICE department missing"}

    existing_streams = {
        s.source_url: s
        for s in db.execute(
            select(StreamSource).where(StreamSource.vms_system == vms.name)
        ).scalars().all()
    }
    created_c = updated_c = created_s = 0
    seen_urls: set[str] = set()

    for c in cams:
        seen_urls.add(c["source_url"])
        code = c["external_ref"]
        cam = db.scalar(select(Camera).where(Camera.camera_code == code))
        if cam is None:
            cam = Camera(camera_code=code, name=c["name"], department_id=dept.department_id, status="ACTIVE")
            if c.get("district"):
                cam.district = c["district"]
            db.add(cam)
            db.flush()
            created_c += 1
        else:
            if cam.name != c["name"]:
                cam.name = c["name"]
                updated_c += 1
        cam.last_seen_at = now

        stream = existing_streams.get(c["source_url"])
        if stream is None:
            stream = StreamSource(
                camera_id=cam.camera_id,
                label=f"{c['name']} · {vms.name}",
                protocol=c["protocol"],
                source_url=c["source_url"],
                vms_system=vms.name,
                department_id=dept.department_id,
                is_live=True,
                enabled=True,
                status="UNKNOWN",
                analytics_enabled=False,
            )
            db.add(stream)
            created_s += 1
        if not stream.enabled:
            stream.enabled = True
        stream.updated_at = now

    disabled = 0
    for url, s in existing_streams.items():
        if url not in seen_urls and s.enabled:
            s.enabled = False
            disabled += 1

    vms.status = "ONLINE"
    vms.last_discovered_at = now
    vms.last_error = None
    db.commit()
    return {
        "vms": vms.name, "ok": True,
        "cameras_created": created_c, "cameras_updated": updated_c,
        "streams_created": created_s, "streams_disabled": disabled,
    }


def sync_all_vms(db: Session) -> dict:
    """Discover from every enabled registered VMS (AC-11 isolation)."""
    ensure_default_registrations(db)
    results = []
    for vms in db.scalars(select(VmsSystem).where(VmsSystem.enabled.is_(True))).all():
        results.append(discover_vms(db, vms))
    return {"results": results, "synced_at": datetime.now(timezone.utc).isoformat()}
