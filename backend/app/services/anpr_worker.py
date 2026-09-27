"""Background ANPR worker (PRD §17 selective AI, TRD 5.6, ADR-006).

Dispatcher over pluggable engines - every detection goes through the shared
pipeline (anpr_pipeline.ingest_observation), never fabricated by the worker:

- edge-ocr  : REAL recognition - ffmpeg frame grab + tesseract OCR on the
              local mediagen plate scenes (protocol EDGE). Never touches the
              real Gujarat Police grid (watch-time quota; honesty guard).
- simulated : legacy random-plate demo, only on protocol-SIM streams; the
              engine label is persisted on every row (PRD §53: an AI
              detection must carry its provenance).

Both loops also sweep stale viewer sessions (existing behaviour kept).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.services import edge_anpr
from app.services.anpr_pipeline import ingest_observation
from app.services.stream_service import sweep_stale_sessions

TICK_INTERVAL_SECONDS = 8
logger = logging.getLogger("sentinel")

# Frames are written to the shared hls volume (mounted read-only by nginx),
# so the browser can fetch evidence snapshots directly (TRD FR-015).
FRAME_DIR = Path("/hls/anpr/evidence")
_FRAME_GEN: dict[str, int] = {}


def _edge_streams(db):
    """Analytics-enabled EDGE streams that point at the local mediagen."""
    from app.models.module2 import StreamSource

    rows = db.execute(
        select(StreamSource).where(
            StreamSource.enabled.is_(True),
            StreamSource.analytics_enabled.is_(True),
            StreamSource.protocol == "EDGE",
        )
    ).scalars().all()
    # Local deterministic scenes: no dependency on the slow round-robin
    # prober's status lifecycle (which is tuned to spare the real grid).
    return [s for s in rows if s.source_url.startswith("http://web/hls/")]


def _edge_tick(db) -> dict:
    """One edge-OCR pass: grab a frame per stream, OCR it, ingest real reads."""
    from app.models.module2 import StreamSource

    counts = {"observations": 0, "events": 0, "alerts": 0}
    streams = _edge_streams(db)
    if not streams:
        return counts

    now_name = int(time.time())
    for s in streams:
        # Rotate filenames so nginx serves a stable, cache-bustable snapshot.
        gen = (_FRAME_GEN.get(s.stream_id, 0) + 1) % 2
        _FRAME_GEN[s.stream_id] = gen
        frame_path = FRAME_DIR / f"{s.stream_id[:8]}_{gen}.jpg"
        if not edge_anpr.extract_frame(s.source_url, frame_path):
            continue
        raw, conf = edge_anpr.ocr_plate(frame_path)
        if not raw:
            continue
        c = ingest_observation(
            db,
            stream_id=s.stream_id, camera_id=s.camera_id,
            plate_raw=raw, confidence=conf, engine="edge-ocr",
            vehicle_class="car",
            captured_at=datetime.now(timezone.utc),
            frame_uri=f"/hls/anpr/evidence/{frame_path.name}",
            meta={"lane": "EDGE-1", "source": "mediagen"},
        )
        counts["observations"] += c["observations"]
        counts["events"] += c["events"]
        counts["alerts"] += c["alerts"]
    if counts["observations"]:
        db.commit()
    return counts


def _sim_tick(db) -> dict:
    """Legacy synthetic engine (SIM protocol only), via the shared pipeline."""
    import random

    rng = random.Random()
    from app.models.module2 import StreamSource

    streams = db.execute(
        select(StreamSource).where(
            StreamSource.enabled.is_(True),
            StreamSource.analytics_enabled.is_(True),
            StreamSource.status == "ONLINE",
            StreamSource.protocol == "SIM",
        )
    ).scalars().all()
    counts = {"observations": 0, "events": 0, "alerts": 0}
    if not streams:
        return counts

    STATES = ["GJ", "MH", "RJ", "MP", "DL"]
    CLASSES = ["car", "car", "bike", "truck", "bus", "auto"]
    now = datetime.now(timezone.utc)
    for s in streams:
        for _ in range(rng.randint(1, 4)):
            state = rng.choice(STATES)
            plate = f"{state}{rng.randint(1, 28):02d}{''.join(rng.choice('ABCDEFGHJKLMNPRSTUVWXYZ') for _ in range(2))}{rng.randint(0, 9999):04d}"
            c = ingest_observation(
                db,
                stream_id=s.stream_id, camera_id=s.camera_id,
                plate_raw=plate, confidence=round(rng.uniform(0.72, 0.985), 3),
                engine="simulated", vehicle_class=rng.choice(CLASSES),
                speed_kmph=round(rng.uniform(15, 95), 1), captured_at=now,
                frame_uri=None, meta={"lane": rng.choice(["L1", "L2", "L3"])},
            )
            counts["observations"] += c["observations"]
            counts["events"] += c["events"]
            counts["alerts"] += c["alerts"]
    db.commit()
    return counts


async def anpr_loop(stop: asyncio.Event):
    """Worker loop: edge OCR every tick; synthetic engine only if SIM feeds exist."""
    while not stop.is_set():
        try:
            db = SessionLocal()
            try:
                edge = _edge_tick(db)
                sim = _sim_tick(db)
                if edge["observations"] or sim["observations"]:
                    logger.info(
                        "anpr tick: edge=%s sim=%s (obs=%d evt=%d alert=%d)",
                        edge["observations"], sim["observations"],
                        edge["observations"] + sim["observations"],
                        edge["events"] + sim["events"], edge["alerts"] + sim["alerts"],
                    )
                sweep_stale_sessions(db)
            finally:
                db.close()
        except Exception:  # pragma: no cover - keep the loop alive
            logger.exception("anpr tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
