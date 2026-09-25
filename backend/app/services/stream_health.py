"""Background health prober: HLS/SIM sources get HEAD/GET probed periodically."""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.module2 import StreamHealthEvent, StreamSource
from app.services.hls_service import probe_health

PROBE_INTERVAL_SECONDS = 45
MAX_HEALTH_ROWS_PER_STREAM = 200


async def probe_all_streams_once() -> dict:
    """Probe every enabled stream once; update status + append health events."""
    db = SessionLocal()
    try:
        streams = db.execute(
            select(StreamSource).where(StreamSource.enabled.is_(True))
        ).scalars().all()
        results = {"checked": 0, "online": 0, "offline": 0}
        for s in streams:
            if s.protocol in {"HLS", "SIM"}:
                status, latency, detail = await probe_health(s)
            else:
                status, latency, detail = "UNKNOWN", None, "probe-not-implemented"
            now = datetime.now(timezone.utc)
            s.status = status
            s.latency_ms = latency
            s.last_probe_at = now
            db.add(StreamHealthEvent(
                stream_id=s.stream_id, status=status, latency_ms=latency,
                detail=detail, checked_at=now,
            ))
            results["checked"] += 1
            results["online" if status == "ONLINE" else "offline"] += 1
        db.commit()
        return results
    finally:
        db.close()


async def health_loop(stop: asyncio.Event):
    while not stop.is_set():
        try:
            await probe_all_streams_once()
        except Exception:  # pragma: no cover - keep the loop alive
            import logging
            logging.getLogger("sentinel").exception("health probe failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=PROBE_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
