"""ANPR Service: YOLO-based Number Plate Detection + In-Memory Crop Caching + pytesseract OCR.

Uses:
- YOLO model (`anpr-demo-model.pt`) for plate detection.
- OpenCV for image preprocessing, cropping, and live HUD visual annotations.
- In-memory bounded cache for cropped plate images (no disk storage needed).
- pytesseract for text recognition with Indian plate normalization.
- Runtime ON/OFF toggle so heavy AI processing only runs when enabled by the user.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

import cv2
import numpy as np

from app.core.config import get_settings
from app.services.anpr_pipeline import looks_like_plate, normalize_plate

logger = logging.getLogger("sentinel.anpr")

# Ensure Tesseract binary is discoverable on Windows
if sys.platform == "win32":
    try:
        import pytesseract

        if not shutil.which("tesseract"):
            win_candidates = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
            ]
            for p in win_candidates:
                if os.path.exists(p):
                    pytesseract.pytesseract.tesseract_cmd = p
                    logger.info("Configured tesseract binary path to: %s", p)
                    break
    except Exception as e:
        logger.warning("Failed to configure pytesseract path: %s", e)


# ---------------------------------------------------------------------------
# In-Memory Plate Crop Cache (No disk storage needed)
# ---------------------------------------------------------------------------

@dataclass
class CachedPlateCrop:
    crop_id: str
    stream_id: str | None
    camera_id: str | None
    plate_text: str
    plate_raw: str
    confidence: float
    yolo_confidence: float
    timestamp: str
    bbox: list[int]  # [x1, y1, x2, y2]
    crop_base64: str
    image_bytes: bytes | None = None

    def to_dict(self, include_bytes: bool = False) -> dict:
        d = {
            "crop_id": str(self.crop_id),
            "stream_id": str(self.stream_id) if self.stream_id is not None else None,
            "camera_id": str(self.camera_id) if self.camera_id is not None else None,
            "plate_text": str(self.plate_text),
            "plate_raw": str(self.plate_raw),
            "confidence": float(self.confidence),
            "yolo_confidence": float(self.yolo_confidence),
            "timestamp": str(self.timestamp),
            "bbox": [int(x) for x in self.bbox],
            "crop_base64": str(self.crop_base64),
        }
        if include_bytes and self.image_bytes is not None:
            d["image_bytes"] = self.image_bytes
        return d


class PlateCropMemoryCache:
    """Thread-safe bounded in-memory LRU cache for detected plate crops."""

    def __init__(self, max_items: int = 150):
        self._max_items = max_items
        self._cache: OrderedDict[str, CachedPlateCrop] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, item: CachedPlateCrop) -> None:
        with self._lock:
            if item.crop_id in self._cache:
                self._cache.move_to_end(item.crop_id)
            self._cache[item.crop_id] = item
            if len(self._cache) > self._max_items:
                self._cache.popitem(last=False)

    def get(self, crop_id: str) -> CachedPlateCrop | None:
        with self._lock:
            item = self._cache.get(crop_id)
            if item:
                self._cache.move_to_end(crop_id)
            return item

    def list_recent(self, stream_id: str | None = None, limit: int = 30) -> list[CachedPlateCrop]:
        with self._lock:
            items = list(self._cache.values())
            if stream_id:
                items = [x for x in items if x.stream_id == stream_id]
            # Most recent first
            return items[::-1][:limit]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._cache)


# Global in-memory cache instance
plate_crop_cache = PlateCropMemoryCache(max_items=200)


# ---------------------------------------------------------------------------
# ANPR State Controller (Start / Stop Toggle)
# ---------------------------------------------------------------------------

class AnprStateController:
    """Manages active state of ANPR so it does NOT run unless toggled ON."""

    def __init__(self):
        self._global_enabled = False
        self._stream_states: dict[str, bool] = {}
        self._lock = threading.Lock()

    def is_enabled(self, stream_id: str | None = None) -> bool:
        with self._lock:
            if stream_id is not None:
                # Per-stream toggle overrides if present, otherwise follows global
                return self._stream_states.get(stream_id, self._global_enabled)
            return self._global_enabled

    def set_enabled(self, stream_id: str | None, enabled: bool) -> bool:
        with self._lock:
            if stream_id:
                self._stream_states[stream_id] = enabled
                logger.info("ANPR stream %s toggled %s", stream_id, "ON" if enabled else "OFF")
            else:
                self._global_enabled = enabled
                logger.info("ANPR global toggled %s", "ON" if enabled else "OFF")
            return enabled

    def get_status(self) -> dict:
        with self._lock:
            active_streams = [s for s, en in self._stream_states.items() if en]
            return {
                "global_enabled": self._global_enabled,
                "active_stream_count": len(active_streams),
                "active_streams": active_streams,
                "cached_plates_count": plate_crop_cache.count(),
            }


anpr_controller = AnprStateController()


# ---------------------------------------------------------------------------
# Model Manager (YOLO11 / YOLOv8 plate detector)
# ---------------------------------------------------------------------------

class YoloPlateDetector:
    """Singleton wrapper around the YOLO number plate model."""

    _instance: YoloPlateDetector | None = None
    _init_lock = threading.Lock()

    def __init__(self):
        self._model = None
        self._model_path = self._resolve_model_path()
        self._warmup_done = False

    @classmethod
    def get_instance(cls) -> YoloPlateDetector:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _resolve_model_path(self) -> Path:
        settings = get_settings()
        configured = getattr(settings, "anpr_model_path", None)
        candidates = []
        if configured:
            candidates.append(Path(configured))
        candidates.extend([
            Path("/app/anpr-demo-model.pt"),
            Path("/app/backend/anpr-demo-model.pt"),
            Path("anpr-demo-model.pt"),
            Path("d:/sentinel-registry/anpr-demo-model.pt"),
            Path("D:/sentinel-registry/anpr-demo-model.pt"),
            Path(__file__).resolve().parent / "anpr-demo-model.pt",
            Path(__file__).resolve().parents[1] / "anpr-demo-model.pt",
            Path(__file__).resolve().parents[2] / "anpr-demo-model.pt",
            Path(__file__).resolve().parents[3] / "anpr-demo-model.pt",
            Path.cwd() / "anpr-demo-model.pt",
            Path.cwd().parent / "anpr-demo-model.pt",
        ])
        for p in candidates:
            if p.exists() and p.is_file():
                logger.info("Resolved ANPR YOLO model path: %s", p)
                return p
        raise FileNotFoundError(f"anpr-demo-model.pt not found in candidate paths: {[str(c) for c in candidates]}")

    def load_model(self):
        if self._model is not None:
            return self._model
        with self._init_lock:
            if self._model is not None:
                return self._model
            try:
                from ultralytics import YOLO

                logger.info("Loading YOLO model from %s...", self._model_path)
                model = YOLO(str(self._model_path))
                # Warmup inference to eliminate first-request latency
                dummy = np.zeros((480, 640, 3), dtype=np.uint8)
                model(dummy, verbose=False)
                self._model = model
                self._warmup_done = True
                logger.info("YOLO ANPR model loaded and warmed up successfully! Classes: %s", model.names)
                return self._model
            except Exception as e:
                logger.exception("Failed to load YOLO model: %s", e)
                raise

    def detect(self, frame: np.ndarray, conf_threshold: float = 0.25) -> list[dict]:
        """Run YOLO inference on a BGR image frame."""
        model = self.load_model()
        results = model(frame, conf=conf_threshold, verbose=False)
        boxes_out = []
        if not results:
            return boxes_out
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return boxes_out

        h, w = frame.shape[:2]
        for box in r.boxes:
            coords = box.xyxy[0].cpu().numpy().tolist()
            conf = float(box.conf[0].cpu().item())
            cls_id = int(box.cls[0].cpu().item())
            cls_name = str(model.names.get(cls_id, "plate"))

            x1 = int(max(0, min(int(coords[0]), w - 1)))
            y1 = int(max(0, min(int(coords[1]), h - 1)))
            x2 = int(max(0, min(int(coords[2]), w)))
            y2 = int(max(0, min(int(coords[3]), h)))

            if x2 > x1 and y2 > y1:
                boxes_out.append({
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "confidence": float(round(conf, 3)),
                    "class_id": int(cls_id),
                    "class_name": str(cls_name),
                })
        return boxes_out


# ---------------------------------------------------------------------------
# OCR Preprocessing & Extraction (pytesseract + OpenCV)
# ---------------------------------------------------------------------------

def preprocess_plate_image(plate_bgr: np.ndarray) -> np.ndarray:
    """OpenCV pipeline to enhance number plate image for Tesseract OCR."""
    if plate_bgr is None or plate_bgr.size == 0:
        return plate_bgr

    # 1. Convert to grayscale
    gray = cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2GRAY)

    # 2. Resize / upscale so character strokes are clear (target height ~70-90px)
    h, w = gray.shape[:2]
    if h < 50 or w < 120:
        scale = max(2.0, min(80.0 / max(1, h), 4.0))
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # 3. Contrast adjustment using CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 4. Bilateral filter to smooth noise while keeping plate edges sharp
    filtered = cv2.bilateralFilter(gray, 9, 75, 75)

    # 5. Otsu thresholding
    _, th = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 6. Add generous border padding for Tesseract edge character recognition
    padded = cv2.copyMakeBorder(th, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return padded


def ocr_plate_crop(crop_bgr: np.ndarray) -> tuple[str, str, float]:
    """Passes cropped plate to pytesseract and returns (plate_normalized, plate_raw, confidence)."""
    import pytesseract

    if crop_bgr is None or crop_bgr.size == 0:
        return "", "", 0.0

    prep = preprocess_plate_image(crop_bgr)
    cfg = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    words: list[str] = []
    confs: list[float] = []

    try:
        data = pytesseract.image_to_data(prep, config=cfg, output_type=pytesseract.Output.DICT)
        for txt, c in zip(data.get("text", []), data.get("conf", [])):
            clean = re.sub(r"[^A-Za-z0-9]", "", txt or "").upper()
            if clean and float(c) > 20:
                words.append(clean)
                confs.append(float(c))
    except Exception as e:
        logger.warning("pytesseract primary pass failed: %s", e)

    # Fallback to adaptive Gaussian threshold if Otsu found nothing
    if not words:
        try:
            gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
            if gray.shape[0] < 50:
                gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
            th2 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11)
            th2 = cv2.copyMakeBorder(th2, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            data2 = pytesseract.image_to_data(th2, config=cfg, output_type=pytesseract.Output.DICT)
            for txt, c in zip(data2.get("text", []), data2.get("conf", [])):
                clean = re.sub(r"[^A-Za-z0-9]", "", txt or "").upper()
                if clean and float(c) > 20:
                    words.append(clean)
                    confs.append(float(c))
        except Exception as e:
            logger.warning("pytesseract fallback pass failed: %s", e)

    if not words:
        return "", "", 0.0

    raw = "".join(words)
    norm = normalize_plate(raw)
    avg_conf = min(max(sum(confs) / len(confs) / 100.0, 0.1), 0.99)
    return norm, raw, round(avg_conf, 3)


# ---------------------------------------------------------------------------
# Frame Annotation with OpenCV (Cyber / Police Tactical HUD Style)
# ---------------------------------------------------------------------------

def draw_tactical_box(
    img: np.ndarray,
    box: list[int],
    color: tuple[int, int, int] = (0, 230, 118),  # Vibrant Emerald (BGR)
    corner_len: int = 15,
    thickness: int = 2,
):
    """Draws a modern tactical bounding box with corner accent brackets."""
    x1, y1, x2, y2 = box
    # Main subtle box
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)

    # Top-Left corner
    cv2.line(img, (x1, y1), (x1 + corner_len, y1), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x1, y1), (x1, y1 + corner_len), color, thickness, cv2.LINE_AA)

    # Top-Right corner
    cv2.line(img, (x2, y1), (x2 - corner_len, y1), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x2, y1), (x2, y1 + corner_len), color, thickness, cv2.LINE_AA)

    # Bottom-Left corner
    cv2.line(img, (x1, y2), (x1 + corner_len, y2), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x1, y2), (x1, y2 - corner_len), color, thickness, cv2.LINE_AA)

    # Bottom-Right corner
    cv2.line(img, (x2, y2), (x2 - corner_len, y2), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x2, y2), (x2, y2 - corner_len), color, thickness, cv2.LINE_AA)


def annotate_frame(
    frame: np.ndarray,
    detections: list[dict],
    show_hud: bool = True,
    fps: float | None = None,
) -> np.ndarray:
    """Draws bounding boxes, plate text labels, confidence scores, and HUD on frame."""
    out = frame.copy()
    h, w = out.shape[:2]

    for det in detections:
        x1, y1, x2, y2 = det["bbox"]
        plate_text = det.get("plate_text") or det.get("plate_raw") or "PLATE"
        conf = det.get("confidence", 0.0)
        yolo_conf = det.get("yolo_confidence", 0.0)

        # High confidence = Emerald (0, 230, 118), Medium = Amber (0, 190, 255)
        color = (0, 230, 118) if conf >= 0.60 else (0, 190, 255)

        # 1. Tactical Box
        draw_tactical_box(out, [x1, y1, x2, y2], color=color, corner_len=min(18, (x2 - x1) // 3))

        # 2. Text Label Pill
        label = f"{plate_text}  {int(conf * 100)}%" if conf > 0 else f"{plate_text} (AI {int(yolo_conf * 100)}%)"
        font = cv2.FONT_HERSHEY_DUPLEX
        font_scale = 0.55
        font_thickness = 1
        (tw, th), baseline = cv2.getTextSize(label, font, font_scale, font_thickness)

        pill_y2 = y1 - 6 if y1 - 6 > th + 10 else y2 + th + 14
        pill_y1 = pill_y2 - th - 8
        pill_x1 = x1
        pill_x2 = min(w - 2, x1 + tw + 16)

        # Dark background pill
        cv2.rectangle(out, (pill_x1, pill_y1), (pill_x2, pill_y2), (18, 20, 24), -1)
        cv2.rectangle(out, (pill_x1, pill_y1), (pill_x2, pill_y2), color, 1, cv2.LINE_AA)

        # Text label
        cv2.putText(
            out,
            label,
            (pill_x1 + 8, pill_y2 - 6),
            font,
            font_scale,
            (255, 255, 255),
            font_thickness,
            cv2.LINE_AA,
        )

    # HUD Status overlay at top
    if show_hud:
        hud_bg_w = min(420, w)
        cv2.rectangle(out, (0, 0), (hud_bg_w, 32), (15, 18, 24), -1)
        cv2.line(out, (0, 32), (hud_bg_w, 32), (0, 230, 118), 1, cv2.LINE_AA)

        # Pulse circle
        cv2.circle(out, (16, 16), 5, (0, 230, 118), -1)
        hud_text = f"ANPR ON  |  YOLO11n + Tesseract  |  Plates: {len(detections)}"
        if fps:
            hud_text += f"  |  {fps:.1f} FPS"
        cv2.putText(out, hud_text, (28, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (230, 235, 240), 1, cv2.LINE_AA)

    return out


# ---------------------------------------------------------------------------
# High-Level Frame Processor
# ---------------------------------------------------------------------------

def process_frame(
    frame: np.ndarray,
    stream_id: str | None = None,
    camera_id: str | None = None,
    conf_threshold: float = 0.25,
    annotate: bool = True,
    save_to_cache: bool = True,
) -> tuple[np.ndarray, list[dict]]:
    """Complete pipeline for a single frame:
    1. Detect plates via YOLO model.
    2. Crop detected plate regions into in-memory cache (no disk writes).
    3. Run OpenCV preprocessing + pytesseract OCR.
    4. Annotate frame with OpenCV bounding boxes and plate labels.
    """
    if frame is None or frame.size == 0:
        return frame, []

    detector = YoloPlateDetector.get_instance()
    raw_boxes = detector.detect(frame, conf_threshold=conf_threshold)

    detections = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for idx, b in enumerate(raw_boxes):
        x1 = int(b["bbox"][0])
        y1 = int(b["bbox"][1])
        x2 = int(b["bbox"][2])
        y2 = int(b["bbox"][3])
        yolo_conf = float(b["confidence"])

        # Extract plate crop in memory
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0 or (x2 - x1) < 12 or (y2 - y1) < 8:
            continue

        # Run OCR
        plate_norm, plate_raw, ocr_conf = ocr_plate_crop(crop)
        ocr_conf = float(ocr_conf)

        # Encode crop to JPEG in RAM for base64 / caching
        ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        crop_bytes = buf.tobytes() if ok else b""
        crop_b64 = f"data:image/jpeg;base64,{base64.b64encode(crop_bytes).decode('ascii')}" if ok else ""

        crop_id = f"crop_{int(time.time() * 1000)}_{idx}_{stream_id or 'cam'}"

        det_dict = {
            "crop_id": str(crop_id),
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "plate_text": str(plate_norm or plate_raw or "PLATE"),
            "plate_raw": str(plate_raw),
            "plate_normalized": str(plate_norm),
            "confidence": float(ocr_conf if ocr_conf > 0 else yolo_conf),
            "yolo_confidence": float(yolo_conf),
            "timestamp": str(now_iso),
            "stream_id": str(stream_id) if stream_id else None,
            "camera_id": str(camera_id) if camera_id else None,
            "crop_base64": str(crop_b64),
        }
        detections.append(det_dict)

        # Store in memory cache
        if save_to_cache and ok:
            cached_item = CachedPlateCrop(
                crop_id=str(crop_id),
                stream_id=str(stream_id) if stream_id else None,
                camera_id=str(camera_id) if camera_id else None,
                plate_text=str(plate_norm or plate_raw or "PLATE"),
                plate_raw=str(plate_raw),
                confidence=float(ocr_conf if ocr_conf > 0 else yolo_conf),
                yolo_confidence=float(yolo_conf),
                timestamp=str(now_iso),
                bbox=[int(x1), int(y1), int(x2), int(y2)],
                crop_base64=str(crop_b64),
                image_bytes=crop_bytes,
            )
            plate_crop_cache.add(cached_item)

    annotated = annotate_frame(frame, detections) if annotate else frame
    return annotated, detections


# ---------------------------------------------------------------------------
# MJPEG Live Stream Generator with Dynamic ON/OFF ANPR
# ---------------------------------------------------------------------------

def generate_anpr_mjpeg_stream(
    source_url_or_index: str | int,
    stream_id: str,
    target_fps: int = 15,
) -> Generator[bytes, None, None]:
    """Generates an MJPEG multipart HTTP stream for a camera or video source.
    If ANPR is toggled ON for this stream: runs YOLO + OCR and overlays boxes.
    If ANPR is toggled OFF: streams native frames directly without AI load.
    """
    cap = cv2.VideoCapture(source_url_or_index)
    if not cap.isOpened():
        logger.error("Could not open video capture for: %s", source_url_or_index)
        return

    frame_interval = 1.0 / max(1, target_fps)
    frame_counter = 0

    try:
        while True:
            t0 = time.time()
            ret, frame = cap.read()
            if not ret or frame is None:
                # If end of video file, loop back to start for smooth demo
                if isinstance(source_url_or_index, str) and not source_url_or_index.startswith("rtsp"):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                    if not ret:
                        break
                else:
                    break

            frame_counter += 1
            is_on = anpr_controller.is_enabled(stream_id)

            if is_on:
                # Run ANPR inference
                annotated, _ = process_frame(
                    frame,
                    stream_id=stream_id,
                    conf_threshold=0.25,
                    annotate=True,
                    save_to_cache=True,
                )
                display_frame = annotated
            else:
                # ANPR is OFF: pass through original frame with minimal watermark
                display_frame = frame
                # Add tiny "ANPR: OFF" indicator in the corner
                cv2.rectangle(display_frame, (10, 10), (120, 32), (20, 24, 30), -1)
                cv2.circle(display_frame, (22, 21), 4, (120, 120, 120), -1)
                cv2.putText(
                    display_frame,
                    "ANPR OFF",
                    (34, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (180, 180, 180),
                    1,
                    cv2.LINE_AA,
                )

            # Encode as JPEG
            ok, jpeg = cv2.imencode(".jpg", display_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
                )

            elapsed = time.time() - t0
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
    finally:
        cap.release()
