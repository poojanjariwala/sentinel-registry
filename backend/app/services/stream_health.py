"""Background health prober: HLS/SIM sources get HEAD/GET probed periodically.

Design rules:
- No DB connection is held while probing: specs are copied out, the session is
  closed, probes run connection-free, then results are written in one short
  transaction (a pooled DB connection must never wait on network I/O).
- Grid (real Gujarat Police) streams are probed round-robin, a few per cycle:
  every probe downloads a full 216 KB archive playlist and the grid enforces a
  per-account watch-time quota, so probing all 30 every cycle would exhaust it.
  4 probes per 45 s cycle means each camera is verified roughly every 5-6 min.
"""

import asyncio
import itertools
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.module2 import StreamHealthEvent, StreamSource
from app.services import grid_client
from app.services.hls_service import OriginSpec, probe_health

PROBE_INTERVAL_SECONDS = 45
GRID_PROBES_PER_CYCLE = 2  # gentle: each grid camera verified ~every 11 min

_grid_probe_cycle: itertools.cycle | None = None
_grid_cycle_ids: list[str] = []


def _grid_probe_subset(ids: list[str]) -> set[str]:
    """Round-robin: return the next GRID_PROBES_PER_CYCLE stream ids."""
    global _grid_probe_cycle, _grid_cycle_ids
    if _grid_probe_cycle is None or _grid_cycle_ids != ids:
        _grid_probe_cycle = itertools.cycle(ids)
        _grid_cycle_ids = ids
    chosen: set[str] = set()
    for _ in range(min(GRID_PROBES_PER_CYCLE, len(ids))):
        chosen.add(next(_grid_probe_cycle))
    return chosen


async def probe_all_streams_once() -> dict:
    """Probe enabled streams once; update status + append health events."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(StreamSource).where(StreamSource.enabled.is_(True))
        ).scalars().all()
        pairs = [(s, OriginSpec.from_source(s)) for s in rows]
    finally:
        db.close()

    grid_pairs = [(s, sp) for s, sp in pairs if grid_client.is_grid_url(sp.source_url)]
    other_pairs = [(s, sp) for s, sp in pairs if not grid_client.is_grid_url(sp.source_url)]

    results = {"checked": 0, "online": 0, "offline": 0}
    if grid_client.in_cooldown():
        # Fail fast during a watch-time backoff; leave grid statuses as-is.
        results["grid_cooldown_skipped"] = len(grid_pairs)
        selected_grid: list[tuple] = []
    else:
        ids = [sp.stream_id for _, sp in grid_pairs]
        chosen = _grid_probe_subset(ids) if ids else set()
        selected_grid = [(s, sp) for s, sp in grid_pairs if sp.stream_id in chosen]

    outcomes: list[tuple[str, str, int | None, str | None]] = []
    for _s, sp in other_pairs + selected_grid:
        if sp.protocol in {"HLS", "SIM"}:
            status, latency, detail = await probe_health(sp)
        else:
            # RTSP (grid inference) sources are health-checked implicitly by
            # the grid-rtsp engine's own reconnect cycle - probing them here
            # would open a second client copy per camera (load etiquette).
            status, latency, detail = "UNKNOWN", None, "probe-not-implemented"
        outcomes.append((sp.stream_id, status, latency, detail))
        results["checked"] += 1
        results["online" if status == "ONLINE" else "offline"] += 1

    # Short write transaction - probes already finished, no connection held.
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for stream_id, status, latency, detail in outcomes:
            stream = db.get(StreamSource, stream_id)
            if stream is None:
                continue
            stream.status = status
            stream.latency_ms = latency
            stream.last_probe_at = now
            db.add(StreamHealthEvent(
                stream_id=stream_id, status=status, latency_ms=latency,
                detail=detail, checked_at=now,
            ))
        db.commit()
    finally:
        db.close()
    return results


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
