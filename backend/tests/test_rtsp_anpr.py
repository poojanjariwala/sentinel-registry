"""Unit tests for the RTSP grid-ANPR engine (pure logic, no DB / no camera).

Mirrors the grid integrator guide's pre-submission checklist where it can be
checked without a live feed.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import grid_client, rtsp_anpr  # noqa: E402
from app.services.rtsp_anpr import (  # noqa: E402
    _backoff_seconds,
    expand_aspect,
    grid_id_of,
    resolve_rtsp_url,
    _union_rect,
)


def test_backoff_is_exponential_with_cap():
    # ~2 s start, doubling, capped at 30 s (guide §3 reconnect rule)
    assert _backoff_seconds(1) == 2.0
    assert _backoff_seconds(2) == 4.0
    assert _backoff_seconds(3) == 8.0
    assert _backoff_seconds(4) == 16.0
    for many in (5, 6, 10, 100):
        assert _backoff_seconds(many) <= 30.0
    assert _backoff_seconds(7) == 30.0


def test_grid_id_extraction():
    assert grid_id_of("rtsp://a:b@1.2.3.4:8554/stream/cam07") == "cam07"
    assert grid_id_of("rtsp://***@host:8554/stream/cam01") == "cam01"
    assert grid_id_of("https://cctv.corp8.cloud/cam01/index.m3u8") == ""
    assert grid_id_of("") == ""


def test_expand_aspect_pads_to_plate_band():
    # tall narrow box -> padded to 2:1
    x, y, w, h = expand_aspect(100, 100, 20, 40, 1920, 1080)
    assert w == 80 and h == 40
    # too wide -> centre-cropped to 7:1
    x, y, w, h = expand_aspect(100, 100, 700, 40, 1920, 1080)
    assert h == 40 and w == 280
    # clamped to frame bounds
    x, y, w, h = expand_aspect(1900, 1070, 20, 40, 1920, 1080)
    assert x + w <= 1920 and y + h <= 1080


def test_union_rect_spans_boxes():
    r = _union_rect([(10, 10, 5, 5), (20, 15, 5, 5)])
    assert r == (10, 10, 15, 10)
    assert _union_rect([]) is None


def test_resolve_rtsp_url_redaction_roundtrip(monkeypatch):
    monkeypatch.setattr(grid_client, "rtsp_configured", lambda: True)
    monkeypatch.setattr(
        grid_client, "camera_rtsp_url",
        lambda gid: f"rtsp://ops%40corp8.cloud:secret@103.250.160.189:8554/stream/{gid}",
    )
    redacted = "rtsp://ops:***@103.250.160.189:8554/stream/cam04"
    out = resolve_rtsp_url(redacted)
    assert out.startswith("rtsp://ops%40corp8.cloud:secret@")
    assert out.endswith("/stream/cam04")
    # no credentials configured -> no URL, engine skips the row
    monkeypatch.setattr(grid_client, "rtsp_configured", lambda: False)
    assert resolve_rtsp_url(redacted) == ""


def test_redact_rtsp_hides_userinfo():
    url = "rtsp://ops%40corp8.cloud:secret@103.250.160.189:8554/stream/cam04"
    red = grid_client.redact_rtsp(url)
    assert "secret" not in red and "ops%40" not in red
    assert "***@103.250.160.189:8554/stream/cam04" in red
