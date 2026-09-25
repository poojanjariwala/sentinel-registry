"""HLS relay: fetch upstream playlist, rewrite segment URIs through signed tokens.

The browser never sees the origin URL; every playlist line is re-signed so the
public endpoint /streams/hls/{stream_id}/{token}/seg/{name} proxies bytes while
authorization stays server-side (viewer session checked at playlist time).
"""

import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import SentinelError
from app.models.module2 import StreamSource

MAX_PLAYLIST_BYTES = 512 * 1024
MAX_SEGMENT_BYTES = 8 * 1024 * 1024

settings = get_settings()
_secret = settings.jwt_secret


def _sign_part(stream_id: str, name: str, ttl: int, session_id: str) -> str:
    import hashlib

    msg = f"{stream_id}/{name}/{session_id}/{ttl}".encode()
    return hashlib.sha256(msg.encode() if isinstance(msg, str) else msg).hexdigest()[:32]


def sign_segment(stream_id: str, name: str, session_id: str, ttl_seconds: int = 300) -> str:
    ttl = int(time.time()) + ttl_seconds
    return f"{ttl}.{_sign_part(stream_id, name, ttl, session_id)}"


def verify_segment_token(stream_id: str, name: str, session_id: str, token: str) -> bool:
    try:
        ttl_s, sig = token.split(".", 1)
        ttl = int(ttl_s)
    except ValueError:
        return False
    if ttl < int(time.time()):
        return False
    return _sign_part(stream_id, name, ttl, session_id) == sig


def _upstream_base(source_url: str) -> str:
    parts = urlsplit(source_url)
    return f"{parts.scheme}://{parts.netloc}{parts.path.rsplit('/', 1)[0]}"


async def fetch_playlist(source: StreamSource, session_id: str) -> tuple[str, dict]:
    """Download the upstream m3u8 and rewrite every URI to our signed proxy."""
    if source.protocol not in {"HLS", "SIM"}:
        raise SentinelError("PROTOCOL_NOT_SUPPORTED", "HLS proxying requires an HLS/SIM source", 400)
    base = _upstream_base(source.source_url)
    headers = {}
    try:
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            resp = await client.get(source.source_url, headers=headers)
            resp.raise_for_status()
            text = resp.text[:MAX_PLAYLIST_BYTES]
            upstream_headers = {
                k.lower(): v for k, v in resp.headers.items()
                if k.lower() in ("cache-control", "content-type")
            }
    except httpx.HTTPError as e:
        raise SentinelError("UPSTREAM_UNAVAILABLE", f"Upstream fetch failed: {type(e).__name__}", 502)

    out_lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            out_lines.append(line)
        else:
            name = line.rsplit("/", 1)[-1]
            token = sign_segment(source.stream_id, name, session_id)
            out_lines.append(f"/api/v1/streams/hls/{source.stream_id}/{session_id}/{token}/seg/{name}")
    rewritten = "\n".join(out_lines) + "\n"
    return rewritten, upstream_headers


async def fetch_segment(source: StreamSource, name: str) -> tuple[bytes, dict]:
    base = _upstream_base(source.source_url)
    url = f"{base}/{name}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content[:MAX_SEGMENT_BYTES]
            headers = {
                k.lower(): v for k, v in resp.headers.items()
                if k.lower() in ("content-type", "cache-control")
            }
            return data, headers
    except httpx.HTTPStatusError as e:
        # Segment rolled off the origin (delete_segments race): 404 lets the
        # player skip it; a hard 502 would abort the whole wall.
        status = e.response.status_code if e.response is not None else 502
        raise SentinelError("SEGMENT_GONE", "Segment no longer available", 404 if status in (404, 410) else 502)
    except httpx.HTTPError as e:
        raise SentinelError("UPSTREAM_UNAVAILABLE", f"Segment fetch failed: {type(e).__name__}", 502)


async def probe_health(source: StreamSource) -> tuple[str, int | None, str | None]:
    """HEAD/GET the playlist to measure availability and latency."""
    import time as _t

    start = _t.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(source.source_url)
            latency = int((_t.perf_counter() - start) * 1000)
            if resp.status_code == 200 and "#EXTM3U" in resp.text[:64]:
                return "ONLINE", latency, None
            return "OFFLINE", latency, f"HTTP {resp.status_code}"
    except httpx.HTTPError as e:
        return "OFFLINE", None, type(e).__name__

