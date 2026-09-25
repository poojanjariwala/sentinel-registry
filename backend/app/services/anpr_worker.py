"""Background simulated-ANPR worker loop (demo engine)."""

import asyncio
import logging

from app.core.db import SessionLocal
from app.services.sentinel_adapter import tick_simulated_anpr
from app.services.stream_service import sweep_stale_sessions

TICK_INTERVAL_SECONDS = 8
logger = logging.getLogger("sentinel")


async def anpr_loop(stop: asyncio.Event):
    while not stop.is_set():
        try:
            db = SessionLocal()
            try:
                tick_simulated_anpr(db, max_new=25)
                sweep_stale_sessions(db)
            finally:
                db.close()
        except Exception:  # pragma: no cover - keep the loop alive
            logger.exception("anpr tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
