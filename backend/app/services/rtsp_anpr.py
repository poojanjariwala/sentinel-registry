"""RTSP-ANPR engine: REAL recognition on the Sentinel Camera Grid (ADR-006).

Consumes the grid's RTSP endpoint (public IP :8554, credentials embedded in
the URL) - the sanctioned AI-inference path per the grid integrator guide.
RTSP bypasses the CDN and the HLS watch-time quota entirely; HLS stays
viewing-only (quota etiquette).

Integrator-guide compliance, rule by rule:
- force TCP transport ......... OPENCV_FFMPEG_CAPTURE_OPTIONS (import time)
- never trust CAP_PROP_FPS .... all timing from CAP_PROP_POS_MSEC (PTS)
- GOP replay on join .......... warmup window discards pre-stabilisation frames
- non-uniform intervals ....... PTS deltas measured, never assumed constant
- reconnect with backoff ...... 2 s doubling, capped at 30 s, per stream
- join decode warnings ........ tolerated, never fatal (mixed H.264/H.265)
- per-camera properties ....... resolution taken from the frame itself
- scene discontinuity ......... hard-cut detector resets de-dupe/state
- consume only ................ read-only captures, nothing pushed to the grid
- pace the load ............... bounded grabs/OCR per tick, capped open captures

Detection: background frame-difference locates moving regions (grid cameras
are static); candidate boxes are OCR'd via the shared edge engine and only
reads passing the pipeline's strict plate gate are persisted (FR-010:
uncertain reads never become asserted identities). Engine label: "grid-rtsp".
"""

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2

from app.core.config import get_settings
from app.services import edge_anpr, grid_client

settings = get_settings()

# §2 Connecting: force TCP before the first VideoCapture is ever created.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

logger = logging.getLogger("sentinel")

RECONNECT_BASE_S = 2.0
RECONNECT_CAP_S = 30.0
WARMUP_PTS_MS = 1500.0          # discard GOP-replay frames right after join
CUT_MEAN_DIFF = 60.0            # global frame diff above this = scene cut
MIN_BOX_AREA_FRAC = 0.0006      # moving-region size band (fractions of frame)
MAX_BOX_AREA_FRAC = 0.05
MIN_PLATE_BOX_W = 48            # px at source resolution; below = unreadable
MIN_READ_INTERVAL_S = 4.0       # same-plate de-dupe window per stream
FRAME_EVERY_N = 2               # analyse every n-th grabbed frame (paced load)
MAX_GRABS_PER_POLL = 25         # drain budget per stream per tick (fast path)
MAX_ANALYSE_PER_POLL = 4        # decode-convert budget per stream per tick
MAX_OCR_PER_TICK = 8            # hard budget: OCR is the expensive step
MAX_CONNECTS_PER_TICK = 3       # pace dial-out attempts (bounded tick latency)
OPEN_TIMEOUT_MS = 8000          # ffmpeg open/read bounds: a filtered host must
READ_TIMEOUT_MS = 8000          # fail fast, not stall the tick for minutes
AUTH_STALL_FAILURES = 5         # persistent auth refusal (401): stop hammering
AUTH_STALL_BACKOFF_S = 600.0    # and re-try only every 10 min until fixed
TICK_SLEEP_SECONDS = 2.0

# Evidence snapshots land next to the edge-engine's, served by nginx.
FRAME_DIR = Path(os.environ.get("SENTINEL_FRAME_DIR", "/hls/anpr/evidence"))
_GEN: dict[str, int] = {}

# One persistent state per stream row (captures survive across ticks).
_STATES: dict[str, "_StreamState"] = {}


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------

def _union_rect(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not boxes:
        return None
    x0 = min(x for x, _y, _w, _h in boxes)
    y0 = min(y for _x, y, _w, _h in boxes)
    x1 = max(x + w for x, _y, w, _h in boxes)
    y1 = max(y + h for _x, y, w, h in boxes)
    return x0, y0, x1 - x0, y1 - y0


def expand_aspect(
    x: int, y: int, w: int, h: int, frame_w: int, frame_h: int,
    ar_lo: float = 2.0, ar_hi: float = 7.0,
) -> tuple[int, int, int, int]:
    """Pad a merged moving-region box to the aspect band of Indian plates.

    Wider-than-band boxes are centre-cropped to ar_hi so the OCR image never
    spans two plates; result is clamped to frame bounds.
    """
    cy, cx = y + h // 2, x + w // 2
    ar = w / max(1, h)
    if ar < ar_lo:
        w2 = int(h * ar_lo)
        x, w = cx - w2 // 2, w2
    elif ar > ar_hi:
        w2 = int(h * ar_hi)
        x, w = cx - w2 // 2, w2
    x = max(0, min(x, frame_w - 1))
    y = max(0, min(y, frame_h - 1))
    return x, y, min(w, frame_w - x), min(h, frame_h - y)


def is_scene_cut(prev_gray: Any, gray: Any) -> bool:
    """Hard-cut detector: one-frame global change this large is a loop cut
    (§3 scene discontinuity), not motion."""
    if prev_gray is None or prev_gray.shape != gray.shape:
        return False
    return float(cv2.absdiff(gray, prev_gray).mean()) > CUT_MEAN_DIFF


def detect_moving_boxes(
    prev_gray: Any, gray: Any,
) -> list[tuple[int, int, int, int]]:
    """Moving regions by frame difference; plausibility-filtered candidates."""
    if prev_gray is None or prev_gray.shape != gray.shape:
        return []
    diff = cv2.absdiff(gray, prev_gray)
    diff = cv2.GaussianBlur(diff, (21, 21), 0)
    _, diff = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    diff = cv2.morphologyEx(
        diff, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)),
    )
    cnts, _ = cv2.findContours(diff, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    farea = gray.shape[0] * gray.shape[1]
    boxes: list[tuple[int, int, int, int]] = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        if not (MIN_BOX_AREA_FRAC * farea <= area <= MAX_BOX_AREA_FRAC * farea):
            continue
        ar = w / max(1, h)
        if not (1.2 <= ar <= 9.0):
            continue
        boxes.append((x, y, w, h))
    return boxes


def resolve_rtsp_url(source_url: str) -> str:
    """Full RTSP URL for a stream row.

    Rows persist the REDACTED url (rtsp://***@host:8554/stream/camNN) so
    credentials never live in the database; this injects them from grid
    settings. Rows carrying explicit credentials are used as-is.
    """
    if "***" not in source_url:
        return source_url
    if not grid_client.rtsp_configured():
        return ""
    m = re.search(r"/stream/([^/?]+)", source_url)
    return grid_client.camera_rtsp_url(m.group(1)) if m else ""


def grid_id_of(source_url: str) -> str:
    m = re.search(r"/stream/([^/?]+)", source_url or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Capture lifecycle (§3 reconnect / warmup / timing rules)
# ---------------------------------------------------------------------------

@dataclass
class _StreamState:
    stream_id: str
    camera_id: str
    label: str
    grid_id: str
    rtsp_url: str = ""
    cap: Any = None
    prev_gray: Any = None
    first_pts_ms: float = -1.0
    last_pts_ms: float = -1.0
    frame_no: int = 0
    consecutive_failures: int = 0
    next_attempt_monotonic: float = 0.0
    warmup_done: bool = False
    last_read: dict = field(default_factory=dict)
    last_cut_log: float = 0.0


def _backoff_seconds(failures: int) -> float:
    """Exponential backoff, ~2 s doubling, capped at 30 s (§3)."""
    return min(RECONNECT_BASE_S * (2 ** max(0, min(failures - 1, 5))), RECONNECT_CAP_S)


def open_capture(rtsp_url: str) -> tuple[Any, str | None]:
    """Open an RTSP capture (TCP forced env-wide) and confirm a first frame.

    Join-time decoder warnings (mixed H.264/H.265 grid) are tolerated: we
    only require that a frame eventually decodes; otherwise the caller
    schedules a backoff reconnect.
    """
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS,
    ])
    if not cap.isOpened():
        cap.release()
        return None, "open-failed"
    try:
        ok, frame = cap.read()
    except Exception as e:  # noqa: BLE001 - decode backend can raise oddities
        cap.release()
        return None, f"first-read:{type(e).__name__}"
    if not ok or frame is None or not frame.size:
        cap.release()
        return None, "no-first-frame"
    return cap, None


def _save_evidence(frame: Any, grid_id: str) -> str | None:
    try:
        gen = _GEN.get(grid_id, 0)
        _GEN[grid_id] = gen ^ 1
        name = f"rtsp_{grid_id}_{gen ^ 1}.jpg"
        path = FRAME_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return f"/hls/anpr/evidence/{name}"
    except Exception:  # noqa: BLE001 - evidence is best-effort
        logger.exception("evidence write failed for %s", grid_id)
        return None


# ---------------------------------------------------------------------------
# Per-stream poll (sync; runs inside a worker thread - decode releases GIL)
# ---------------------------------------------------------------------------

def _poll_stream(
    st: _StreamState, reads: list[dict], ocr_budget: list[int],
    conn_budget: list[int],
) -> dict:
    """Bounded per-tick work for one stream: connect if due (paced by
    conn_budget), then drain up to MAX_GRABS_PER_POLL packets, analysing at
    most MAX_ANALYSE_PER_POLL frames. Draining fast (grab, no frame convert)
    lets a poll catch up to the live edge after idle periods."""
    out = {"grabs": 0, "analysed": 0, "reads": 0}

    if st.cap is None:
        if not st.rtsp_url or time.monotonic() < st.next_attempt_monotonic:
            return out
        if conn_budget[0] <= 0:
            return out  # dial-out budget spent this tick; try again next tick
        conn_budget[0] -= 1
        opened, err = open_capture(st.rtsp_url)
        if opened is None:
            st.consecutive_failures += 1
            wait = _backoff_seconds(st.consecutive_failures)
            # The 2 s -> 30 s backoff is for transient drops (§3); a persistent
            # authorisation refusal (401 on DESCRIBE) is not transient - the
            # account is not on the RTSP access list yet. Stall politely:
            # 30 s cycling over 30 cameras is still a dial-out every second.
            if st.consecutive_failures >= AUTH_STALL_FAILURES and err == "open-failed":
                wait = max(wait, AUTH_STALL_BACKOFF_S)
            st.next_attempt_monotonic = time.monotonic() + wait
            logger.warning(
                "rtsp connect failed (%s) for %s; retry in %.0fs", err, st.grid_id, wait,
            )
            return out
        st.cap = opened
        st.prev_gray = None
        st.first_pts_ms = st.last_pts_ms = -1.0
        st.frame_no = 0
        st.warmup_done = False
        st.consecutive_failures = 0
        st.last_read.clear()  # fresh stream, fresh de-dupe state
        logger.info("rtsp connected: %s (%s)", st.grid_id, st.label)

    cap = st.cap
    analysed = 0
    for _grab in range(MAX_GRABS_PER_POLL):
        if not cap.grab():
            # Feed ended: supervised feeds restart; backoff and reconnect (§3).
            cap.release()
            st.cap = None
            st.consecutive_failures += 1
            st.next_attempt_monotonic = time.monotonic() + _backoff_seconds(st.consecutive_failures)
            logger.info("rtsp feed ended for %s; backoff reconnect scheduled", st.grid_id)
            return out
        out["grabs"] += 1
        st.frame_no += 1
        pts = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0)  # PTS, never FPS math

        if st.frame_no % FRAME_EVERY_N:
            continue
        if analysed >= MAX_ANALYSE_PER_POLL:
            break
        ok, frame = cap.retrieve()
        if not ok or frame is None or not getattr(frame, "size", 0):
            continue
        analysed += 1
        out["analysed"] += 1

        if st.first_pts_ms < 0:
            st.first_pts_ms = pts
        if not st.warmup_done:
            # §3: on join the gateway replays buffered GOPs; early frames are
            # compressed in time and may predate the first IDR. Skip until
            # PTS has advanced a stabilisation window past the first frame.
            if pts - st.first_pts_ms < WARMUP_PTS_MS:
                st.prev_gray = None
                continue
            st.warmup_done = True
        st.last_pts_ms = pts

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if is_scene_cut(st.prev_gray, gray):
            st.prev_gray = gray
            st.last_read.clear()  # §3: hard cut -> reset long-lived state
            if time.time() - st.last_cut_log > 60:
                st.last_cut_log = time.time()
                logger.info("scene discontinuity on %s: state reset", st.grid_id)
            continue
        boxes = detect_moving_boxes(st.prev_gray, gray)
        st.prev_gray = gray

        if not boxes or ocr_budget[0] <= 0:
            continue
        fh, fw = gray.shape[:2]
        mb = _union_rect(boxes)
        if mb is None:
            continue
        x, y, w, h = expand_aspect(mb[0], mb[1], mb[2], mb[3], fw, fh)
        if w < MIN_PLATE_BOX_W:
            continue
        roi = frame[y:y + h, x:x + w]
        if roi.size == 0:
            continue

        raw, conf = edge_anpr.ocr_plate_image(roi)
        ocr_budget[0] -= 1
        if not raw:
            continue
        from app.services.anpr_pipeline import looks_like_plate, normalize_plate

        norm = normalize_plate(raw)
        if not looks_like_plate(norm):
            continue  # FR-010: uncertain reads never become identities
        now_mono = time.monotonic()
        if now_mono - st.last_read.get(norm, 0.0) < MIN_READ_INTERVAL_S:
            continue
        st.last_read[norm] = now_mono
        if len(st.last_read) > 64:
            st.last_read = {
                k: v for k, v in st.last_read.items() if v > now_mono - 300
            } or st.last_read
        out["reads"] += 1
        reads.append({
            "stream_id": st.stream_id,
            "camera_id": st.camera_id,
            "label": st.label,
            "grid_id": st.grid_id,
            "plate_raw": raw,
            "plate_normalized": norm,
            "confidence": conf,
            "pts_ms": pts,
            "frame": frame,
        })
    return out


# ---------------------------------------------------------------------------
# Engine tick + loop wiring
# ---------------------------------------------------------------------------

def reconcile_states(targets: dict[str, dict]) -> None:
    """Drop states whose stream row vanished/disabled; release their captures."""
    for sid in list(_STATES):
        if sid not in targets:
            st = _STATES.pop(sid)
            if st.cap is not None:
                st.cap.release()


def grid_rtsp_tick() -> dict:
    """One RTSP-engine pass. Owns its short DB sessions (never holds a pooled
    connection across network I/O); safe to run via asyncio.to_thread."""
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.models.module2 import StreamSource
    from app.services.anpr_pipeline import ingest_observation

    max_streams = max(1, int(settings.grid_rtsp_max_streams))

    db = SessionLocal()
    targets: dict[str, dict] = {}
    try:
        rows = db.execute(
            select(StreamSource).where(
                StreamSource.enabled.is_(True),
                StreamSource.analytics_enabled.is_(True),
                StreamSource.protocol == "RTSP",
                StreamSource.vms_system == grid_client.GRID_VMS,
            )
        ).scalars().all()
        for s in rows:
            if len(targets) >= max_streams:
                break
            gid = grid_id_of(s.source_url)
            url = resolve_rtsp_url(s.source_url)
            if not gid or not url:
                continue
            targets[s.stream_id] = {
                "camera_id": s.camera_id, "label": s.label, "grid_id": gid, "url": url,
            }
    finally:
        db.close()

    reconcile_states(targets)
    for sid, t in targets.items():
        st = _STATES.get(sid)
        if st is None:
            st = _STATES[sid] = _StreamState(
                stream_id=sid, camera_id=t["camera_id"],
                label=t["label"], grid_id=t["grid_id"],
            )
        st.rtsp_url = t["url"]

    reads: list[dict] = []
    ocr_budget = [MAX_OCR_PER_TICK]
    conn_budget = [MAX_CONNECTS_PER_TICK]
    for st in _STATES.values():
        if ocr_budget[0] <= 0 and st.cap is None:
            continue  # don't open new captures once the OCR budget is spent
        try:
            _poll_stream(st, reads, ocr_budget, conn_budget)
        except Exception:  # noqa: BLE001 - one bad stream never kills the tick
            logger.exception("rtsp poll failed for %s", st.grid_id)
            if st.cap is not None:
                st.cap.release()
                st.cap = None
            st.consecutive_failures += 1
            st.next_attempt_monotonic = time.monotonic() + _backoff_seconds(st.consecutive_failures)

    counts = {"observations": 0, "events": 0, "alerts": 0}
    if reads:
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            for r in reads:
                frame_uri = _save_evidence(r.pop("frame"), r["grid_id"])
                c = ingest_observation(
                    db,
                    stream_id=r["stream_id"], camera_id=r["camera_id"],
                    plate_raw=r["plate_raw"], confidence=r["confidence"],
                    engine="grid-rtsp", vehicle_class=None,
                    captured_at=now, frame_uri=frame_uri,
                    meta={
                        "lane": "RTSP", "source": "grid-rtsp",
                        "grid_id": r["grid_id"], "pts_ms": round(r["pts_ms"], 1),
                    },
                )
                counts["observations"] += c["observations"]
                counts["events"] += c["events"]
                counts["alerts"] += c["alerts"]
            db.commit()
        finally:
            db.close()
    if counts["observations"]:
        logger.info(
            "grid-rtsp tick: %d observations (%d events, %d alerts) across %d captures",
            counts["observations"], counts["events"], counts["alerts"], len(_STATES),
        )
    return counts


def release_all() -> None:
    """Close every open capture (used on shutdown / tests)."""
    for st in _STATES.values():
        if st.cap is not None:
            st.cap.release()
            st.cap = None
    _STATES.clear()


async def grid_rtsp_loop(stop: asyncio.Event) -> None:
    """Standalone loop variant. The ANPR worker instead calls grid_rtsp_tick()
    via to_thread on the shared cadence (see anpr_worker.anpr_loop)."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(grid_rtsp_tick)
        except Exception:  # pragma: no cover - keep the loop alive
            logger.exception("grid rtsp tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SLEEP_SECONDS)
        except asyncio.TimeoutError:
            pass
