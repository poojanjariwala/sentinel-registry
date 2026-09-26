"""Sentinel sandbox adapter: catalogue sync + simulated ANPR worker.

Real deployments swap `sync_catalogue` for the Sentinel /api/ingest feed and
`tick_simulated_anpr` for a frame-grabbing inference worker; the storage and
API contracts stay identical (adapter pattern per TRD ARCH-007).
"""

import asyncio
import random
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.camera import Camera
from app.models.module2 import (
    StreamAlert, StreamSource, TaggedEvent, VehicleObservation, WatchlistVehicle,
)

settings = get_settings()

EVENT_TYPES = ["ANPR", "ANPR", "ANPR", "OVERSPEED", "WRONG_SIDE", "LOITERING"]
VEHICLE_CLASSES = ["car", "car", "bike", "truck", "bus", "auto"]
STATES = ["GJ", "MH", "RJ", "MP", "DL", "PB", "KA"]


def _random_plate(rng: random.Random) -> str:
    state = rng.choice(STATES)
    district = f"{rng.randint(1, 28):02d}"
    letters = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(2))
    digits = f"{rng.randint(0, 9999):04d}"
    return f"{state}{district}{letters}{digits}"


def sync_catalogue(db: Session) -> dict:
    """Import Sentinel sandbox catalogue into stream_sources (idempotent)."""
    base = (settings.sentinel_api_base or "").strip().rstrip("/")
    created = updated = disabled = 0
    cams = {c.camera_code: c for c in db.execute(select(Camera)).scalars().all()}

    async def _fetch():
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(f"{base}/api/ingest")
            r.raise_for_status()
            return r.json()

    if not base:
        return {"ok": False, "reason": "SENTINEL_API_BASE not configured", "created": 0, "updated": 0, "disabled": 0}

    try:
        catalogue = asyncio.get_event_loop().run_until_complete(_fetch())
    except Exception as e:  # noqa: BLE001 - adapter boundary: report, don't crash
        return {"ok": False, "reason": f"{type(e).__name__}: {e}", "created": 0, "updated": 0, "disabled": 0}

    items = catalogue.get("cameras") or catalogue.get("items") or []
    seen_ids = set()
    for item in items:
        sid = str(item.get("id") or item.get("camera_id") or "").strip()
        if not sid:
            continue
        seen_ids.add(sid)
        # Match a registry camera by code, else fall back to name match.
        cam = cams.get(sid) or next((c for code, c in cams.items() if item.get("name", "").lower() in c.name.lower()), None)
        if cam is None:
            continue
        hls = item.get("hls") or item.get("hls_url") or ""
        rtsp = item.get("rtsp") or item.get("rtsp_url") or ""
        url = hls or rtsp
        if not url:
            continue
        protocol = "HLS" if hls else "RTSP"
        existing = db.execute(
            select(StreamSource).where(
                StreamSource.camera_id == cam.camera_id,
                StreamSource.source_url == url,
            )
        ).scalar_one_or_none()
        if existing:
            existing.label = item.get("name") or existing.label
            existing.status = "ONLINE" if item.get("live", True) else "OFFLINE"
            existing.last_probe_at = datetime.now(timezone.utc)
            updated += 1
        else:
            db.add(StreamSource(
                camera_id=cam.camera_id,
                label=item.get("name") or f"{cam.name} (Sentinel {sid})",
                protocol=protocol,
                source_url=url,
                vms_system="SENTINEL",
                department_id=cam.department_id,
                is_live=True,
                status="ONLINE" if item.get("live", True) else "OFFLINE",
                last_probe_at=datetime.now(timezone.utc),
            ))
            created += 1

    # Sentinel streams no longer present get disabled, not deleted (audit trail).
    for s in db.execute(select(StreamSource).where(StreamSource.vms_system == "SENTINEL", StreamSource.enabled.is_(True))).scalars().all():
        marker = re.search(r"/stream/([^/]+)/", s.source_url)
        if marker and marker.group(1) not in seen_ids:
            s.enabled = False
            disabled += 1

    db.commit()
    return {"ok": True, "source": base, "created": created, "updated": updated, "disabled": disabled}


def seed_simulated_feeds(db: Session) -> dict:
    """Create demo streams across distinct 'VMS systems' (deliverable:
    feeds from at least two different systems). Deterministic and idempotent.

    Sources point at the local mediagen HLS scenes (cam1..cam3) which the
    gateway proxies; each scene cycles so multiple cameras share a scene.
    Only touches SIM VMS markers - real grid feeds (GP-GRID) are never
    rewritten by the self-heal below.
    """
    created = 0
    cams = db.execute(
        select(Camera).where(Camera.status == "ACTIVE", Camera.latitude.is_not(None)).limit(60)
    ).scalars().all()
    existing = {
        (s.camera_id, s.vms_system)
        for s in db.execute(select(StreamSource)).scalars().all()
    }
    base = settings.sentinel_hls_base.rstrip("/")
    # .../hls/cam1 -> .../hls/camN
    root = base.rsplit("/cam", 1)[0]
    # Self-heal: refresh SIM streams whose stored URL no longer matches the
    # current media root (e.g. mediagen container replaced an external host).
    all_sim = db.execute(
        select(StreamSource).where(StreamSource.vms_system.in_(["GUJCAMS-SIM", "CITYCORE-SIM"]))
    ).scalars().all()
    refreshed = 0
    for s in all_sim:
        if not s.source_url.startswith(root):
            scene = (int(s.source_url[-6]) if s.source_url[-7:-6].isdigit() else 1) if "/cam" in s.source_url else (hash(s.camera_id) % 3) + 1
            s.source_url = f"{root}/cam{scene}/index.m3u8"
            refreshed += 1
    if refreshed:
        db.commit()
    for i, cam in enumerate(cams):
        vms = "GUJCAMS-SIM" if i % 2 == 0 else "CITYCORE-SIM"
        if (cam.camera_id, vms) in existing:
            continue
        scene = (i % 3) + 1
        db.add(StreamSource(
            camera_id=cam.camera_id,
            label=f"{cam.name} · live",
            protocol="SIM",
            source_url=f"{root}/cam{scene}/index.m3u8",
            vms_system=vms,
            department_id=cam.department_id,
            is_live=True,
            enabled=True,
            status="ONLINE",
            analytics_enabled=i % 3 == 0,
            last_probe_at=datetime.now(timezone.utc),
        ))
        created += 1
    db.commit()
    return {"created": created, "refreshed": refreshed, "vms_systems": ["GUJCAMS-SIM", "CITYCORE-SIM", "SENTINEL"]}


def seed_watchlist(db: Session, user_id: str) -> int:
    if db.execute(select(WatchlistVehicle).limit(1)).scalar_one_or_none():
        return 0
    plates = [
        ("GJ01AB1234", "Stolen vehicle - Ahmedabad FIR 214/2026", "CRITICAL", "Demo Owner A"),
        ("GJ18KB5678", "Wanted in toll-evasion + robbery case", "HIGH", "Demo Owner B"),
        ("MH12DE9012", "Suspect vehicle - interstate intel input", "HIGH", "Demo Owner C"),
        ("GJ27BU4455", "Missing person case - associated vehicle", "MEDIUM", "Demo Owner D"),
    ]
    now = datetime.now(timezone.utc)
    for plate, reason, sev, owner in plates:
        db.add(WatchlistVehicle(
            plate_normalized=plate, reason=reason, severity=sev,
            owner_hint=owner, created_by=user_id, created_at=now,
        ))
    db.commit()
    return len(plates)


def tick_simulated_anpr(db: Session, max_new: int = 25) -> dict:
    """One worker tick: generate ANPR observations on analytics-enabled streams,
    create tagged events, and raise alerts for watchlist hits."""
    rng = random.Random()
    now = datetime.now(timezone.utc)

    streams = db.execute(
        select(StreamSource).where(
            StreamSource.enabled.is_(True),
            StreamSource.analytics_enabled.is_(True),
            StreamSource.status == "ONLINE",
            # Honesty guard: simulated ANPR never fabricates observations for
            # real feeds (HLS/RTSP/ONVIF). Real ANPR is a separate engine (ADR-006).
            StreamSource.protocol == "SIM",
        )
    ).scalars().all()
    if not streams:
        return {"observations": 0, "events": 0, "alerts": 0}

    watch = {
        w.plate_normalized: w
        for w in db.execute(select(WatchlistVehicle)).scalars().all()
        if w.valid_until is None or w.valid_until > now
    }

    obs_count = evt_count = alert_count = 0
    for s in streams:
        for _ in range(rng.randint(1, 4)):
            plate = _random_plate(rng)
            # Guarantee periodic watchlist hits so the demo shows alerts.
            if watch and rng.random() < 0.12:
                plate = rng.choice(list(watch.keys()))
            raw = f"{plate[:2]}-{plate[2:4]} {plate[4:6]} {plate[6:]}"
            obs = VehicleObservation(
                stream_id=s.stream_id, camera_id=s.camera_id, captured_at=now,
                plate_raw=raw, plate_normalized=normalize_plate(plate),
                vehicle_class=rng.choice(VEHICLE_CLASSES),
                speed_kmph=round(rng.uniform(15, 95), 1),
                confidence=round(rng.uniform(0.72, 0.985), 3),
                engine="simulated",
                snapshot_hint=f"frame://{s.stream_id}/{int(now.timestamp())}",
                meta={"lane": rng.choice(["L1", "L2", "L3"]), "direction": rng.choice(["N", "S", "E", "W"])},
            )
            db.add(obs)
            db.flush()
            obs_count += 1

            if rng.random() < 0.35 or obs.plate_normalized in watch:
                evt_type = "ANPR" if obs.plate_normalized in watch else rng.choice(EVENT_TYPES)
                sev = "HIGH" if obs.plate_normalized in watch else ("MEDIUM" if evt_type != "ANPR" else "INFO")
                db.add(TaggedEvent(
                    stream_id=s.stream_id, camera_id=s.camera_id,
                    observation_id=obs.observation_id,
                    event_type=evt_type,
                    label=f"{evt_type} {obs.plate_normalized} @ {s.label}",
                    occurred_at=now, severity=sev,
                    created_by=None, meta={"engine": "simulated"},
                ))
                evt_count += 1

            w = watch.get(obs.plate_normalized)
            if w:
                recent = db.execute(
                    select(StreamAlert).where(
                        StreamAlert.watch_id == w.watch_id,
                        StreamAlert.raised_at > now - timedelta(minutes=10),
                    )
                ).scalar_one_or_none()
                if recent is None:  # de-dupe: one alert per 10 min per watch entry
                    db.add(StreamAlert(
                        observation_id=obs.observation_id, watch_id=w.watch_id,
                        plate_normalized=obs.plate_normalized,
                        stream_id=s.stream_id, camera_id=s.camera_id,
                        raised_at=now, severity=w.severity, status="OPEN",
                    ))
                    alert_count += 1

    db.commit()
    return {"observations": obs_count, "events": evt_count, "alerts": alert_count}


def normalize_plate(raw: str) -> str:
    up = (raw or "").upper()
    up = up.replace("O", "0")
    return re.sub(r"[^A-Z0-9]", "", up)
