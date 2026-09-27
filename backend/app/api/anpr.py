"""ANPR API Endpoints: YOLO-based Detection, In-Memory Crop Cache, pytesseract OCR, and ON/OFF Control."""

from __future__ import annotations

import base64
import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, require_perm
from app.core.errors import SentinelError, request_id_var
from app.models.module2 import StreamSource
from app.models.user import User
from app.services import audit as audit_svc
from app.services.anpr_pipeline import ingest_observation, looks_like_plate, normalize_plate
from app.services.anpr_service import (
    AnprStateController,
    CachedPlateCrop,
    YoloPlateDetector,
    anpr_controller,
    generate_anpr_mjpeg_stream,
    plate_crop_cache,
    process_frame,
)

logger = logging.getLogger("sentinel.anpr.api")

router = APIRouter(prefix="/anpr", tags=["anpr"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AnprToggleRequest(BaseModel):
    stream_id: str | None = Field(default=None, description="Stream ID to toggle, or null for global toggle")
    enabled: bool = Field(description="True to start ANPR, False to turn it off")


class FrameDetectionRequest(BaseModel):
    image_base64: str = Field(description="Base64 encoded frame (JPEG/PNG or data URL)")
    stream_id: str | None = Field(default=None, description="Optional stream ID")
    camera_id: str | None = Field(default=None, description="Optional camera ID")
    conf_threshold: float = Field(default=0.25, ge=0.05, le=0.95)
    persist_observation: bool = Field(default=True, description="Whether to ingest into VehicleObservation DB")


# ---------------------------------------------------------------------------
# Status & Runtime Control Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
def get_anpr_status(
    stream_id: str | None = None,
    user: User = Depends(require_perm("camera", "read")),
):
    """Returns ANPR runtime state, model info, active streams, and in-memory cache counts."""
    status = anpr_controller.get_status()
    stream_active = anpr_controller.is_enabled(stream_id) if stream_id else status["global_enabled"]
    return {
        "data": {
            **status,
            "stream_active": stream_active,
            "model": "YOLO11n (Plate Detection)",
            "ocr_engine": "Tesseract OCR (OpenCV Preprocessed)",
        },
        "meta": {},
        "requestId": request_id_var.get(),
    }


@router.post("/toggle")
def toggle_anpr(
    req: AnprToggleRequest,
    request: Request,
    user: User = Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    """Start or Stop ANPR processing on live feed or globally.
    Saves processing resources when turned OFF.
    """
    new_state = anpr_controller.set_enabled(req.stream_id, req.enabled)

    # If stream_id provided, sync analytics_enabled on StreamSource
    if req.stream_id:
        src = db.get(StreamSource, req.stream_id)
        if src:
            src.analytics_enabled = req.enabled
            db.commit()

    audit_svc.record(
        db,
        "ANPR_TOGGLE",
        "stream" if req.stream_id else "system",
        req.stream_id or "global",
        after_state={"enabled": new_state, "stream_id": req.stream_id},
        actor_user_id=user.user_id,
        actor_label=user.email,
        ip_address=request.client.host if request.client else None,
    )

    return {
        "data": {
            "stream_id": req.stream_id,
            "enabled": new_state,
            "message": f"ANPR {'STARTED' if new_state else 'STOPPED'}"
            + (f" for stream {req.stream_id}" if req.stream_id else " globally"),
            "status": anpr_controller.get_status(),
        },
        "meta": {},
        "requestId": request_id_var.get(),
    }


# ---------------------------------------------------------------------------
# Live Frame Detection & OCR (YOLO + OpenCV Preprocessing + pytesseract)
# ---------------------------------------------------------------------------

@router.post("/detect-frame")
def detect_frame(
    req: FrameDetectionRequest,
    user: User = Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    """Processes a single video/live feed frame:
    1. Checks if ANPR is enabled (or forces if user explicitly requested detection).
    2. Runs YOLO model to detect license plates.
    3. Crops plate into in-memory cache (no disk writes).
    4. Preprocesses with OpenCV and runs pytesseract OCR.
    5. Returns bounding boxes, normalized plate text, confidence, and in-memory crop base64.
    6. Ingests into DB observations and checks watchlist if enabled.
    """
    # Decode base64 frame
    raw_b64 = req.image_base64
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]

    try:
        img_bytes = base64.b64decode(raw_b64)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            raise ValueError("Decoded image is empty")
    except Exception as e:
        raise SentinelError("INVALID_IMAGE", f"Failed to decode image frame: {e}", 400)

    # Check ANPR enabled state
    is_active = anpr_controller.is_enabled(req.stream_id)

    # Run detection + crop + OCR pipeline
    _, detections = process_frame(
        frame,
        stream_id=req.stream_id,
        camera_id=req.camera_id,
        conf_threshold=req.conf_threshold,
        annotate=False,
        save_to_cache=True,
    )

    # Ingest observations into DB for analytics & watchlist alerts
    alerts_fired = 0
    if req.persist_observation and req.stream_id and detections:
        src = db.get(StreamSource, req.stream_id)
        cam_id = req.camera_id or (src.camera_id if src else None)
        if cam_id:
            for det in detections:
                plate_txt = det["plate_text"]
                if plate_txt and plate_txt != "PLATE":
                    try:
                        counts = ingest_observation(
                            db,
                            stream_id=req.stream_id,
                            camera_id=cam_id,
                            plate_raw=det["plate_raw"] or plate_txt,
                            confidence=det["confidence"],
                            engine="yolo11-anpr",
                            captured_at=datetime.now(timezone.utc),
                            frame_uri=det.get("crop_base64"),
                            meta={
                                "bbox": det["bbox"],
                                "yolo_conf": det["yolo_confidence"],
                                "crop_id": det["crop_id"],
                            },
                        )
                        alerts_fired += counts.get("alerts", 0)
                    except Exception as ex:
                        logger.warning("Failed to ingest observation: %s", ex)
            db.commit()

    return {
        "data": {
            "anpr_active": is_active,
            "plate_count": len(detections),
            "detections": detections,
            "alerts_fired": alerts_fired,
        },
        "meta": {},
        "requestId": request_id_var.get(),
    }


# ---------------------------------------------------------------------------
# In-Memory Cache Endpoints (Access cached cropped plates without disk storage)
# ---------------------------------------------------------------------------

@router.get("/cache")
def list_cached_crops(
    stream_id: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(require_perm("camera", "read")),
):
    """Returns recent cropped number plate images from in-memory cache."""
    crops = plate_crop_cache.list_recent(stream_id=stream_id, limit=limit)
    return {
        "data": [c.to_dict(include_bytes=False) for c in crops],
        "meta": {"total": plate_crop_cache.count(), "limit": limit},
        "requestId": request_id_var.get(),
    }


@router.get("/cache/{crop_id}/image")
def get_cached_crop_image(crop_id: str):
    """Serves the raw JPEG bytes of a cached crop directly from memory."""
    crop = plate_crop_cache.get(crop_id)
    if not crop or not crop.image_bytes:
        raise SentinelError("CROP_NOT_FOUND", "Cropped plate not found in memory cache", 404)
    return Response(content=crop.image_bytes, media_type="image/jpeg")


@router.post("/cache/clear")
def clear_cache(user: User = Depends(require_perm("camera", "read"))):
    """Clears the in-memory cropped plate cache."""
    plate_crop_cache.clear()
    return {"data": {"cleared": True}, "meta": {}, "requestId": request_id_var.get()}


# ---------------------------------------------------------------------------
# Live Annotated Stream Endpoint (OpenCV MJPEG Feed with ANPR Overlay)
# ---------------------------------------------------------------------------

@router.get("/live/{stream_id}")
def live_anpr_mjpeg_stream(
    stream_id: str,
    anpr: bool | None = None,
    db: Session = Depends(get_db),
):
    """Streams live MJPEG video with real-time OpenCV HUD annotations.
    Controlled by the ANPR ON/OFF state or `anpr` query parameter.
    """
    src = db.get(StreamSource, stream_id)
    if not src:
        raise HTTPException(status_code=404, detail="Stream not found")

    if anpr is not None:
        anpr_controller.set_enabled(stream_id, anpr)

    source_url = src.source_url
    # For local testing or if source is mock, resolve properly
    return StreamingResponse(
        generate_anpr_mjpeg_stream(source_url, stream_id=stream_id, target_fps=15),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# Video File Upload & Analysis
# ---------------------------------------------------------------------------

@router.post("/analyze-file")
async def analyze_uploaded_file(
    file: UploadFile = File(...),
    conf_threshold: float = Form(0.25),
    user: User = Depends(require_perm("camera", "read")),
):
    """Analyzes an uploaded image or short video file with the YOLO + pytesseract ANPR model."""
    contents = await file.read()
    if not contents:
        raise SentinelError("EMPTY_FILE", "Uploaded file is empty", 400)

    filename = (file.filename or "").lower()
    is_image = any(filename.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"])

    if is_image:
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            raise SentinelError("DECODE_ERROR", "Could not decode image", 400)

        annotated, detections = process_frame(
            frame,
            stream_id="upload",
            conf_threshold=conf_threshold,
            annotate=True,
            save_to_cache=True,
        )
        _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
        annotated_b64 = f"data:image/jpeg;base64,{base64.b64encode(jpeg.tobytes()).decode('ascii')}"

        return {
            "data": {
                "type": "image",
                "filename": file.filename,
                "plate_count": len(detections),
                "detections": detections,
                "annotated_image": annotated_b64,
            },
            "meta": {},
            "requestId": request_id_var.get(),
        }

    # Video file analysis: save temporarily to memory/scratch and sample keyframes
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_f:
        tmp_f.write(contents)
        temp_path = Path(tmp_f.name)

    try:
        cap = cv2.VideoCapture(str(temp_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        # Sample every 5th frame or 2 frames per sec
        step = max(1, int(fps / 2))

        all_detections = []
        frame_idx = 0

        while cap.isOpened() and frame_idx < min(total_frames, 300):
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            if frame_idx % step == 0:
                _, detections = process_frame(
                    frame,
                    stream_id="upload_video",
                    conf_threshold=conf_threshold,
                    annotate=False,
                    save_to_cache=True,
                )
                sec = float(round(float(frame_idx) / float(fps), 2))
                for d in detections:
                    d["video_timestamp_sec"] = sec
                    all_detections.append(d)
            frame_idx += 1
        cap.release()

        # Deduplicate detections by plate text within window
        unique_plates: dict[str, dict] = {}
        for d in all_detections:
            p = str(d["plate_text"])
            if p not in unique_plates or float(d["confidence"]) > float(unique_plates[p]["confidence"]):
                unique_plates[p] = d

        return {
            "data": {
                "type": "video",
                "filename": str(file.filename or ""),
                "total_frames_analyzed": int(frame_idx),
                "detected_plates": list(unique_plates.values()),
                "total_unique_plates": int(len(unique_plates)),
            },
            "meta": {},
            "requestId": request_id_var.get(),
        }
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
