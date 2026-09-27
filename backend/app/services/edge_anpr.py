"""Edge-ANPR engine: REAL plate recognition on demo edge scenes (ADR-006).

Pulls a recent frame from an HLS source (ffmpeg, local mediagen only),
reads the plate with tesseract OCR, and pushes it through the shared
pipeline. No random plate generation - observations come from pixels.

Etiquette + safety:
- demo scenes only: NEVER runs against the real Gujarat Police grid HLS
  origin (quota + watch-time). Sources must be http://web/hls/... .
  The RTSP grid engine (rtsp_anpr) is the sanctioned grid-inference path.
- bounded: one ffmpeg invocation + one OCR per stream per tick.
"""

import logging
import re
import subprocess
from pathlib import Path

from app.services.anpr_pipeline import normalize_plate

logger = logging.getLogger("sentinel")

FRAME_TTL_READS = 2  # each cached frame is consumed by at most 2 ticks


def extract_frame(source_url: str, out_path: Path, timeout: float = 8.0) -> bool:
    """Grab one frame near the live edge via ffmpeg. Local sources only."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-live_start_index", "-2", "-timeout", "5000000",
        "-i", source_url, "-frames:v", "1", str(out_path),
    ]
    try:
        subprocess.run(cmd, timeout=timeout, check=True, capture_output=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning("frame grab failed for %s: %s", source_url, type(e).__name__)
        return False
    return out_path.exists() and out_path.stat().st_size > 0


def ocr_plate_image(img) -> tuple[str, float]:
    """Read a plate from a BGR image via tesseract.

    General-purpose path: the edge demo scenes crop their known ROI first and
    delegate here; the RTSP grid engine (rtsp_anpr) feeds full candidate
    crops. Grayscale -> upscale -> Otsu, with an adaptive-threshold fallback.
    Returns ("", 0.0) when nothing readable was found.
    """
    try:
        import cv2
        import pytesseract
    except ImportError:  # pragma: no cover - engine deps missing
        logger.warning("edge-ANPR deps missing (opencv/pytesseract)")
        return "", 0.0
    if img is None or not getattr(img, "size", 0):
        return "", 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    return _ocr_gray(gray, cv2, pytesseract)


def ocr_plate(image_path: Path) -> tuple[str, float]:
    """Read a plate from an image file (edge demo scenes).

    The demo plate is white-on-dark at a known region (mediagen draws the
    plate box at x=230..490, y=140..214); crop exactly, then delegate to the
    general OCR path.
    """
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        return "", 0.0
    roi = img[140:214, 230:490]
    if roi.size == 0:
        return "", 0.0
    return ocr_plate_image(roi)


def _ocr_gray(gray, cv2, pytesseract) -> tuple[str, float]:
    """Whitelist OCR over a prepared grayscale plate image."""
    _, th = cv2.threshold(gray, 0, 255, cv2.CV_8U + cv2.THRESH_OTSU)
    th = cv2.copyMakeBorder(th, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    cfg = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    data = pytesseract.image_to_data(th, config=cfg, output_type=pytesseract.Output.DICT)
    words, confs = [], []
    for txt, conf in zip(data["text"], data["conf"]):
        t = re.sub(r"[^A-Za-z0-9]", "", txt or "")
        if t and float(conf) > 30:
            words.append(t)
            confs.append(float(conf))
    if not words:
        # Fallback: adaptive threshold (robust to uneven lighting).
        th2 = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10,
        )
        th2 = cv2.copyMakeBorder(th2, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        data = pytesseract.image_to_data(th2, config=cfg, output_type=pytesseract.Output.DICT)
        for txt, conf in zip(data["text"], data["conf"]):
            t = re.sub(r"[^A-Za-z0-9]", "", txt or "")
            if t and float(conf) > 30:
                words.append(t)
                confs.append(float(conf))
    if not words:
        return "", 0.0
    return "".join(words), min(max(sum(confs) / len(confs) / 100.0, 0.05), 0.99)
