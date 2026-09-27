"""Shared ANPR observation pipeline (PRD §18, TRD §13).

`ingest_observation()` is the ONE path any engine (edge OCR, future GPU
service, benchmark tools) uses to persist a detection and evaluate watchlist
alerts. Engines only detect; this module decides what a detection means.
Guarantees (TRD §13/§53):
- plate_raw and plate_normalized stored separately;
- every record carries engine name + confidence (never a bare identity);
- watchlist match -> TaggedEvent + StreamAlert, de-duplicated per window.
"""

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.module2 import StreamAlert, TaggedEvent, VehicleObservation, WatchlistVehicle

OCR_CONFUSIONS = str.maketrans({"O": "0", "I": "1", "Q": "0"})


def normalize_plate(raw: str) -> str:
    """TRD §13 controlled rule set: uppercase, strip non-alnum, OCR-confusion map."""
    up = (raw or "").upper().translate(OCR_CONFUSIONS)
    return re.sub(r"[^A-Z0-9]", "", up)


def looks_like_plate(norm: str) -> bool:
    """Accept India-format plates: 2 letters + 1-2 digits + 1-3 letters + 4 digits.

    Exactly 4 digits in the final group (registration numbers are 0001-9999);
    stricter than necessary on purpose - FR-010: uncertain reads must never
    become asserted identities.
    """
    return bool(re.fullmatch(r"[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}", norm))


def single_char_distance(a: str, b: str) -> bool:
    """True when equal-length strings differ in exactly one character
    (single OCR slip, e.g. GJ0LAB1234 vs GJ01AB1234)."""
    if len(a) != len(b) or not a:
        return False
    return sum(1 for x, y in zip(a, b) if x != y) == 1


def possible_watch_match(norm: str, watch_plates: list[str]) -> str | None:
    """FR-010: an uncertain OCR read yields a POSSIBLE match, never an identity.

    Returns the watchlist plate it plausibly is, or None. Exact match wins;
    otherwise a single-character difference at >=2 extra digits of context
    (10+ chars) qualifies as a possible match worth surfacing for review.
    """
    if norm in watch_plates:
        return norm
    if len(norm) < 10:
        return None
    for wp in watch_plates:
        if len(wp) == len(norm) and single_char_distance(norm, wp):
            return wp
    return None


def ingest_observation(
    db: Session,
    *,
    stream_id: str,
    camera_id: str,
    plate_raw: str,
    confidence: float,
    engine: str,
    vehicle_class: str | None = None,
    speed_kmph: float | None = None,
    captured_at: datetime | None = None,
    frame_uri: str | None = None,
    meta: dict | None = None,
) -> dict:
    """Persist one detection through the shared pipeline. Returns counters."""
    now = captured_at or datetime.now(timezone.utc)
    norm = normalize_plate(plate_raw)

    obs = VehicleObservation(
        stream_id=stream_id, camera_id=camera_id, captured_at=now,
        plate_raw=plate_raw, plate_normalized=norm,
        vehicle_class=vehicle_class, speed_kmph=speed_kmph,
        confidence=round(float(confidence), 3), engine=engine,
        snapshot_hint=frame_uri, meta=meta,
    )
    db.add(obs)
    db.flush()
    counts = {"observations": 1, "events": 0, "alerts": 0}

    watch = {
        w.plate_normalized: w
        for w in db.execute(select(WatchlistVehicle)).scalars().all()
        if w.valid_until is None or w.valid_until > now
    }
    w = watch.get(norm)
    possible = None if w else possible_watch_match(norm, list(watch.keys()))

    if w or possible or looks_like_plate(norm):
        sev = w.severity if w else ("MEDIUM" if possible else "INFO")
        label_plate = norm or plate_raw
        if possible:
            label_plate = f"{norm} (possible {possible})"
        db.add(TaggedEvent(
            stream_id=stream_id, camera_id=camera_id, observation_id=obs.observation_id,
            event_type="ANPR",
            label=f"ANPR {label_plate} @ stream {stream_id[:8]}",
            occurred_at=now, severity=sev, created_by=None,
            meta={"engine": engine, "watchlist": bool(w), "possible_match": possible},
        ))
        counts["events"] += 1

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
                plate_normalized=norm, stream_id=stream_id, camera_id=camera_id,
                raised_at=now, severity=w.severity, status="OPEN",
            ))
            counts["alerts"] += 1

    return counts
