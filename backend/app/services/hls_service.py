"""HLS relay: fetch upstream playlist, rewrite segment URIs through signed tokens.

The browser never sees the origin URL; every playlist line is re-signed so the
public endpoint /streams/hls/{stream_id}/{session_id}/{token}/seg/{name} proxies
bytes while authorization stays server-side (viewer session checked at playlist
time).

Origins come in two flavours:
- plain HTTP origins (local mediagen demo scenes, generic VMS exports): fetched
  directly, optionally with per-source headers from stream_sources.auth_json;
- the password-gated Sentinel Camera Grid (cctv.corp8.cloud): fetched through
  grid_client (cookie session + browser headers). The grid publishes AES-128
  encrypted 12-hour looping VOD archives; this module turns each archive into a
  rolling live window (last WINDOW_SEGMENTS segments ending at the real-time
  position) so tiles behave like control-room feeds and viewers are naturally
  desynchronized. The decryption key URI is rewritten through a signed key-proxy
  route. Credentials never reach the browser (ADR-005/ADR-007).
"""

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.core.errors import SentinelError
from app.models.module2 import StreamSource
from app.services import grid_client


@dataclass
class OriginSpec:
    """Connection-free snapshot of a stream's origin settings.

    Request handlers must copy these fields out of the DB session and close
    the session BEFORE awaiting upstream fetches - a pooled DB connection is
    a scarce shared resource and must never be held across slow I/O.
    """

    stream_id: str
    source_url: str
    protocol: str
    auth_json: dict | None

    @classmethod
    def from_source(cls, s: "StreamSource") -> "OriginSpec":
        return cls(
            stream_id=s.stream_id,
            source_url=s.source_url,
            protocol=s.protocol,
            auth_json=s.auth_json if isinstance(s.auth_json, dict) else None,
        )


MAX_PLAYLIST_BYTES = 512 * 1024
MAX_SEGMENT_BYTES = 8 * 1024 * 1024
WINDOW_SEGMENTS = 40  # ~4 minutes at the grid's ~6 s segments
ROLL_INTERVAL_SECONDS = 60  # window end advances once per minute

# The grid CDN can take seconds to serve its 216 KB playlists and hls.js
# reloads them every ~7 s per tile; a short cache keeps the wall smooth and
# the origin load light. Keyed by source_url, valid for grid feeds only.
_GRID_PLAYLIST_TTL = 30.0
_grid_playlist_cache: dict[str, tuple[float, str]] = {}

settings = get_settings()
_secret = settings.jwt_secret


def _sign_part(stream_id: str, name: str, ttl: int, session_id: str) -> str:
    """HMAC over the token fields, keyed by the server secret.

    Every field except the key is visible in the URL, so the signature must
    be keyed - otherwise tokens are forgeable by anyone who has seen one URL.
    """
    import hashlib
    import hmac

    msg = f"{stream_id}/{name}/{session_id}/{ttl}".encode()
    return hmac.new(_secret.encode(), msg, hashlib.sha256).hexdigest()[:32]


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


def _origin_headers(spec: OriginSpec) -> dict[str, str]:
    """Static headers for plain origins (per-source auth extras in auth_json)."""
    headers: dict[str, str] = {}
    extra = spec.auth_json
    if extra:
        if extra.get("cookie"):
            headers["Cookie"] = str(extra["cookie"])
        if extra.get("bearer"):
            headers["Authorization"] = f"Bearer {extra['bearer']}"
        for k, v in (extra.get("headers") or {}).items():
            headers[str(k)] = str(v)
    return headers


async def _fetch_upstream(url: str, spec: OriginSpec, *, timeout: float) -> httpx.Response:
    """Fetch an origin URL, routing grid origins through the authed client."""
    if grid_client.is_grid_url(url):
        return await grid_client.authed_get(url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        return await client.get(url, headers=_origin_headers(spec))


def _parse_playlist(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Split into header tags and (extinf, segment_name) pairs; drop VOD markers.

    Upstream #EXTM3U and #EXT-X-MEDIA-SEQUENCE are dropped - the rolling-window
    emitter supplies its own.
    """
    headers: list[str] = []
    segments: list[tuple[str, str]] = []
    extinf: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-ENDLIST"):
            continue  # looping archive: suppress the VOD end marker
        if line.startswith("#EXTM3U") or line.startswith("#EXT-X-MEDIA-SEQUENCE"):
            continue
        if line.startswith("#EXTINF"):
            extinf = line
        elif line.startswith("#"):
            headers.append(line)
        else:
            segments.append((extinf or "#EXTINF:6.000,", line.rsplit("/", 1)[-1]))
            extinf = None
    return headers, segments


def _rewrite_to_rolling_window(
    spec: OriginSpec, text: str, session_id: str
) -> str:
    """Emit the last WINDOW_SEGMENTS entries ending at the real-time position."""
    headers, segments = _parse_playlist(text)
    total = len(segments)
    if total == 0:
        raise SentinelError("UPSTREAM_INVALID", "Upstream playlist has no segments", 502)

    # Real-time position inside the looping archive (rolls every minute).
    end_idx = (int(time.time()) // ROLL_INTERVAL_SECONDS) % total
    window = [segments[(end_idx - i) % total] for i in range(min(WINDOW_SEGMENTS, total))]
    window.reverse()  # chronological order
    start_seq = (end_idx - len(window) + 1) % total

    out: list[str] = ["#EXTM3U", f"#EXT-X-MEDIA-SEQUENCE:{start_seq}"]
    for h in headers:
        if h.startswith("#EXT-X-PLAYLIST-TYPE"):
            continue  # rolling window is EVENT-like, not VOD
        if h.startswith("#EXT-X-KEY"):
            # Proxy the decryption key through a signed route so the browser
            # never needs grid credentials (URI is quoted inside the tag).
            import re

            m = re.search(r'URI="([^"]+)"', h)
            if m:
                key_name = m.group(1).rsplit("/", 1)[-1]
                token = sign_segment(spec.stream_id, key_name, session_id)
                proxied = (
                    f"/api/v1/streams/hls/{spec.stream_id}/{session_id}/{token}/key/{key_name}"
                )
                h = re.sub(r'URI="[^"]+"', f'URI="{proxied}"', h)
        out.append(h)
    for extinf_line, name in window:
        token = sign_segment(spec.stream_id, name, session_id)
        out.append(extinf_line)
        out.append(f"/api/v1/streams/hls/{spec.stream_id}/{session_id}/{token}/seg/{name}")
    return "\n".join(out) + "\n"


def _rewrite_direct(spec: OriginSpec, text: str, session_id: str) -> str:
    """Original behaviour for genuine live playlists (mediagen demo scenes)."""
    out_lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            out_lines.append(line)
        else:
            name = line.rsplit("/", 1)[-1]
            token = sign_segment(spec.stream_id, name, session_id)
            out_lines.append(f"/api/v1/streams/hls/{spec.stream_id}/{session_id}/{token}/seg/{name}")
    return "\n".join(out_lines) + "\n"


async def _fetch_grid_playlist_cached(spec: OriginSpec) -> str:
    import time as _t

    key = spec.source_url
    hit = _grid_playlist_cache.get(key)
    now = _t.monotonic()
    if hit and now - hit[0] < _GRID_PLAYLIST_TTL:
        return hit[1]
    resp = await _fetch_upstream(spec.source_url, spec, timeout=12.0)
    resp.raise_for_status()
    text = resp.text[:MAX_PLAYLIST_BYTES]
    if "#EXTM3U" not in text[:64]:
        # Session bounced to the login page (followed to a 200 HTML body).
        raise SentinelError("GRID_AUTH_FAILED", "Grid session rejected; check GRID credentials", 502)
    _grid_playlist_cache[key] = (now, text)
    if len(_grid_playlist_cache) > 256:  # bound memory
        _grid_playlist_cache.clear()
    return text


async def fetch_playlist(spec: OriginSpec, session_id: str) -> tuple[str, dict]:
    """Download the upstream m3u8 and rewrite every URI to our signed proxy."""
    if spec.protocol not in {"HLS", "SIM"}:
        raise SentinelError("PROTOCOL_NOT_SUPPORTED", "HLS proxying requires an HLS/SIM source", 400)
    is_grid = grid_client.is_grid_url(spec.source_url)
    try:
        if is_grid:
            text = await _fetch_grid_playlist_cached(spec)
        else:
            resp = await _fetch_upstream(spec.source_url, spec, timeout=6.0)
            resp.raise_for_status()
            text = resp.text[:MAX_PLAYLIST_BYTES]
        upstream_headers = {
            k.lower(): v for k, v in resp.headers.items()
            if k.lower() in ("cache-control", "content-type")
        } if not is_grid else {"content-type": "application/vnd.apple.mpegurl", "cache-control": "no-store"}
    except httpx.HTTPError as e:
        raise SentinelError("UPSTREAM_UNAVAILABLE", f"Upstream fetch failed: {type(e).__name__}", 502)

    if is_grid:
        rewritten = _rewrite_to_rolling_window(spec, text, session_id)
    else:
        rewritten = _rewrite_direct(spec, text, session_id)
    return rewritten, upstream_headers


async def fetch_key(spec: OriginSpec, name: str) -> bytes:
    """Proxy an AES-128 decryption key for grid feeds (signed route only).

    HLS key URIs may be playlist-relative (seg dir) or origin-absolute
    ("/enc.key" on the grid) - try both locations, first 200 wins.
    """
    parts = urlsplit(spec.source_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    seg_dir = f"{origin}{parts.path.rsplit('/', 1)[0]}"
    last_err = "unknown"
    for base in (seg_dir, origin):
        try:
            resp = await _fetch_upstream(f"{base}/{name}", spec, timeout=12.0)
            if resp.status_code == 200 and resp.content:
                return resp.content
            if resp.status_code == 403 and "watch time" in resp.text.lower():
                raise SentinelError("GRID_COOLDOWN", "Grid watch-time quota exhausted", 502)
            last_err = f"HTTP {resp.status_code} at {base}/{name}"
        except httpx.HTTPError as e:
            last_err = f"{type(e).__name__} at {base}/{name}"
    raise SentinelError("KEY_UNAVAILABLE", f"Decryption key unavailable ({last_err})", 502)


async def fetch_segment(spec: OriginSpec, name: str) -> tuple[bytes, dict]:
    base = _upstream_base(spec.source_url)
    url = f"{base}/{name}"
    is_grid = grid_client.is_grid_url(url)
    try:
        resp = await _fetch_upstream(url, spec, timeout=15.0)
        if is_grid and "/auth/login" in str(resp.url):
            raise SentinelError("GRID_AUTH_FAILED", "Grid session expired", 502)
        resp.raise_for_status()
        data = resp.content[:MAX_SEGMENT_BYTES]
        headers = {
            k.lower(): v for k, v in resp.headers.items()
            if k.lower() in ("content-type", "cache-control")
        }
        return data, headers
    except SentinelError:
        raise
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else 502
        if status == 403 and "watch time" in (e.response.text or "").lower():
            raise SentinelError("GRID_COOLDOWN", "Grid watch-time quota exhausted", 502)
        # Segment rolled off the origin (delete_segments race): 404 lets the
        # player skip it; a hard 502 would abort the whole wall.
        raise SentinelError("SEGMENT_GONE", "Segment no longer available", 404 if status in (404, 410) else 502)
    except httpx.HTTPError as e:
        raise SentinelError("UPSTREAM_UNAVAILABLE", f"Segment fetch failed: {type(e).__name__}", 502)


async def probe_health(spec: OriginSpec) -> tuple[str, int | None, str | None]:
    """GET the playlist to measure availability and latency."""
    import time as _t

    start = _t.perf_counter()
    try:
        resp = await _fetch_upstream(spec.source_url, spec, timeout=8.0)
        latency = int((_t.perf_counter() - start) * 1000)
        bounced = grid_client.is_grid_url(spec.source_url) and "/auth/login" in str(resp.url)
        if bounced:
            return "OFFLINE", latency, "GRID_AUTH_EXPIRED"
        if resp.status_code == 200 and "#EXTM3U" in resp.text[:64]:
            return "ONLINE", latency, None
        return "OFFLINE", latency, f"HTTP {resp.status_code}"
    except SentinelError as e:
        # Unconfigured/failed grid auth must not kill the whole probe cycle.
        return "OFFLINE", int((_t.perf_counter() - start) * 1000), e.code
    except httpx.HTTPError as e:
        return "OFFLINE", None, type(e).__name__
