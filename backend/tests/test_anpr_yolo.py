"""Tests for YOLO-based ANPR Pipeline, In-Memory Crop Cache, and OCR."""

import os
import sys
import numpy as np
import cv2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.anpr_service import (
    AnprStateController,
    CachedPlateCrop,
    PlateCropMemoryCache,
    YoloPlateDetector,
    anpr_controller,
    draw_tactical_box,
    ocr_plate_crop,
    plate_crop_cache,
    preprocess_plate_image,
    process_frame,
)
from app.services.anpr_pipeline import normalize_plate


def test_yolo_model_loads_and_properties():
    """Verify that YOLO model (anpr-demo-model.pt) loads and has correct metadata."""
    detector = YoloPlateDetector.get_instance()
    model = detector.load_model()
    assert model is not None
    # Class 0 must be 'plate'
    assert 0 in model.names
    assert model.names[0] == "plate"


def test_in_memory_crop_cache():
    """Verify that plate crops are stored strictly in RAM with LRU capacity."""
    cache = PlateCropMemoryCache(max_items=3)

    item1 = CachedPlateCrop(
        crop_id="c1",
        stream_id="s1",
        camera_id="cam1",
        plate_text="GJ01AB1234",
        plate_raw="GJ01AB1234",
        confidence=0.92,
        yolo_confidence=0.88,
        timestamp="2026-09-27T12:00:00Z",
        bbox=[100, 100, 200, 150],
        crop_base64="data:image/jpeg;base64,abc",
    )
    cache.add(item1)
    assert cache.count() == 1
    assert cache.get("c1") is not None
    assert cache.get("c1").plate_text == "GJ01AB1234"

    # Add items up to and exceeding capacity
    for i in range(2, 5):
        cache.add(
            CachedPlateCrop(
                crop_id=f"c{i}",
                stream_id="s1",
                camera_id="cam1",
                plate_text=f"GJ01AB123{i}",
                plate_raw=f"GJ01AB123{i}",
                confidence=0.90,
                yolo_confidence=0.85,
                timestamp="2026-09-27T12:00:00Z",
                bbox=[100, 100, 200, 150],
                crop_base64="data:image/jpeg;base64,abc",
            )
        )

    # Max items is 3, so c1 was evicted
    assert cache.count() == 3
    assert cache.get("c1") is None
    assert cache.get("c4") is not None

    recent = cache.list_recent()
    assert len(recent) == 3
    assert recent[0].crop_id == "c4"

    cache.clear()
    assert cache.count() == 0


def test_anpr_controller_start_stop():
    """Verify Start and Off toggle behavior (global and per-stream)."""
    ctrl = AnprStateController()

    # Starts in OFF mode so zero AI resources are wasted
    assert ctrl.is_enabled() is False
    assert ctrl.is_enabled("stream-1") is False

    # Start ANPR globally
    ctrl.set_enabled(None, True)
    assert ctrl.is_enabled() is True
    assert ctrl.is_enabled("stream-1") is True

    # Turn OFF globally
    ctrl.set_enabled(None, False)
    assert ctrl.is_enabled() is False

    # Turn ON for a specific stream only
    ctrl.set_enabled("stream-1", True)
    assert ctrl.is_enabled("stream-1") is True
    assert ctrl.is_enabled("stream-2") is False

    # Turn OFF for that stream
    ctrl.set_enabled("stream-1", False)
    assert ctrl.is_enabled("stream-1") is False


def test_opencv_preprocessing_and_ocr():
    """Test OpenCV image enhancement and pytesseract text extraction on a synthetic plate."""
    # Create synthetic number plate image: white rectangle with black text
    plate_img = np.full((70, 220, 3), 255, dtype=np.uint8)
    cv2.putText(plate_img, "GJ01AB1234", (15, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)

    # Preprocess
    prep = preprocess_plate_image(plate_img)
    assert prep is not None
    assert prep.ndim == 2  # Grayscale thresholded
    assert prep.shape[0] >= 50

    # OCR
    norm, raw, conf = ocr_plate_crop(plate_img)
    assert len(raw) > 0
    assert "GJ" in norm or "AB" in norm or "1234" in norm
    assert conf > 0.0


def test_process_frame_annotation():
    """Verify that process_frame detects or annotates frames with OpenCV tactical HUD."""
    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Add dummy car body + plate
    cv2.rectangle(test_frame, (100, 100), (500, 400), (120, 40, 40), -1)
    cv2.rectangle(test_frame, (240, 280), (380, 330), (255, 255, 255), -1)
    cv2.putText(test_frame, "GJ01AB1234", (245, 315), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

    annotated, detections = process_frame(
        test_frame,
        stream_id="test_stream",
        conf_threshold=0.10,
        annotate=True,
        save_to_cache=True,
    )

    assert annotated is not None
    assert annotated.shape == test_frame.shape
