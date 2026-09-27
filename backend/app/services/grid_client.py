"""Sentinel Camera Grid client: authenticated access to the real Gujarat Police
HLS origin (cctv.corp8.cloud).

The grid is password-gated: a form POST to /auth/login sets an HttpOnly session
cookie that must accompany every catalogue/playlist/segment fetch. This module
keeps one process-wide AsyncClient (cookie jar) on the api event loop and
re-authenticates transparently when the grid expires the session. Credentials
and cookies never leave the api container; the browser only ever talks to our
signed HLS gateway (ADR-005).
"""

import asyncio
import re
import time

import httpx

from app.core.config import get_settings
from app.core.errors import SentinelError

settings = get_settings()

GRID_VMS = "GP-GRID"  # vms_system marker for real grid feeds
_LOGIN_PATH = "/auth/login"
_LOGIN_COOLDOWN_SECONDS = 5.0

_lock = asyncio.Lock()
_client: httpx.AsyncClient | None = None
_logged_in = False
_last_login_at = 0.0
_last_login_failed = False
_cooldown_until = 0.0

# The grid enforces a per-account watch-time quota; when it is exhausted the
# login endpoint answers 403 "watch time limit reached". We stop contacting
# the origin entirely until the cooldown passes (fail-fast, no retry storm).
_COOLDOWN_MARKERS = ("watch time limit", "cooldown")
_WATCH_TIME_COOLDOWN_SECONDS = 1800  # backoff window after a quota 403 (30 min)
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "*/*",
}


class GridAuthError(SentinelError):
    def __init__(self, message: str, code: str = "GRID_AUTH_FAILED"):
        super().__init__(code, message, 502)


def base_url() -> str:
    return (settings.grid_base_url or "").strip().rstrip("/")


def configured() -> bool:
    return bool(base_url()) and bool(settings.grid_email) and bool(settings.grid_password)


def is_grid_url(url: str) -> bool:
    base = base_url()
    return bool(base) and url.startswith(base + "/")


def camera_hls_url(grid_id: str) -> str:
    return f"{base_url()}/{grid_id}/index.m3u8"


def rtsp_configured() -> bool:
    """RTSP inference is opt-in via GRID_RTSP_HOST (integrator guide §1)."""
    return bool((settings.grid_rtsp_host or "").strip())


def camera_rtsp_url(grid_id: str) -> str:
    """rtsp://<email>:<password>@<host>:8554/stream/<id>

    The '@' in the account email must be percent-encoded as %40 (guide §1).
    The password is embedded per the guide's contract; callers must never log
    the result - redact_rtsp() exists for that.
    """
    from urllib.parse import quote

    host = (settings.grid_rtsp_host or "").strip()
    email = quote((settings.grid_email or "").strip(), safe="")  # @ -> %40
    password = quote(settings.grid_password or "", safe="")
    return f"rtsp://{email}:{password}@{host}:{settings.grid_rtsp_port}/stream/{grid_id}"


def redact_rtsp(url: str) -> str:
    """Strip userinfo from an rtsp URL for logs/DB labels. Greedy so it also
    covers raw emails whose '@' was not percent-encoded (userinfo itself
    contains a literal '@' up to the final host separator)."""
    return re.sub(r"(rtsp://).+@", r"\1***@", url)


def in_cooldown() -> bool:
    return time.time() < _cooldown_until


def cooldown_remaining_seconds() -> int:
    return max(0, int(_cooldown_until - time.time()))


def _check_config() -> None:
    if in_cooldown():
        raise GridAuthError(
            f"grid watch-time cooldown active; retry in ~{cooldown_remaining_seconds()}s",
            code="GRID_COOLDOWN",
        )
    if not base_url():
        raise GridAuthError("GRID_BASE_URL not configured")
    if not settings.grid_email or not settings.grid_password:
        raise GridAuthError("GRID_EMAIL/GRID_PASSWORD not configured")


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=base_url(),
            timeout=10.0,
            follow_redirects=True,
            headers={**_BROWSER_HEADERS, "Referer": base_url() + "/"},
        )
    return _client


def _bounced_to_login(resp: httpx.Response) -> bool:
    # A real bounce is a redirect to the login page (followed to 200 HTML) or
    # an explicit 401. A plain 403 is NOT a bounce: the grid 403s unauthorised
    # resources (e.g. key/segment locations) with a valid session, and
    # re-logging-in on every 403 floods the login endpoint - the origin then
    # throttles the account and every live tile dies at once.
    return "/auth/login" in str(resp.url) or resp.status_code == 401


async def _login(client: httpx.AsyncClient) -> None:
    """Form-post credentials; the grid sets the HttpOnly session cookie."""
    global _last_login_at, _logged_in, _last_login_failed, _cooldown_until
    # Cooldown only after a FAILED attempt so a valid session is never
    # rejected just because a probe ran recently.
    if _last_login_failed and time.time() - _last_login_at < _LOGIN_COOLDOWN_SECONDS:
        raise GridAuthError("grid login recently failed; cooling down")
    resp = await client.post(
        _LOGIN_PATH,
        data={"email": settings.grid_email, "password": settings.grid_password},
    )
    if resp.status_code == 200 and len(client.cookies) > 0:
        _logged_in = True
        _last_login_failed = False
        return
    if resp.status_code == 403 and any(m in resp.text.lower() for m in _COOLDOWN_MARKERS):
        # Watch-time quota exhausted: back off hard so we never hammer the
        # origin (one login attempt per backoff window at most).
        _cooldown_until = time.time() + _WATCH_TIME_COOLDOWN_SECONDS
        raise GridAuthError(
            f"grid watch-time quota exhausted; backing off for {cooldown_remaining_seconds()}s",
            code="GRID_COOLDOWN",
        )
    if resp.status_code == 403:
        # A bare 403 (no watch-time text) on the login form itself means the
        # origin is throttling the account. Back off with the same window so
        # the flood stops and the quota recovers; the user-facing effect
        # ("cooldown, retry later") is identical to the quota case.
        _cooldown_until = time.time() + _WATCH_TIME_COOLDOWN_SECONDS
        raise GridAuthError(
            f"grid login throttled (HTTP 403); backing off for {cooldown_remaining_seconds()}s",
            code="GRID_COOLDOWN",
        )
    _logged_in = False
    _last_login_failed = True
    _last_login_at = time.time()
    raise GridAuthError(f"grid login failed (HTTP {resp.status_code}); check GRID_EMAIL/GRID_PASSWORD")


async def authed_get(path_or_url: str, *, _retried: bool = False) -> httpx.Response:
    """GET a grid path with the session cookie; re-login once if bounced."""
    global _logged_in
    _check_config()
    client = await _get_client()
    if not _logged_in:
        async with _lock:
            if not _logged_in:
                await _login(client)
    resp = await client.get(path_or_url)
    if _bounced_to_login(resp) and not _retried:
        async with _lock:
            _logged_in = False
            await _login(client)
        return await authed_get(path_or_url, _retried=True)
    return resp


async def fetch_camera_catalogue() -> list[dict]:
    """Fetch cameras.json - the source of truth for the camera set."""
    resp = await authed_get("/cameras.json")
    if resp.status_code != 200:
        raise GridAuthError(f"catalogue fetch failed (HTTP {resp.status_code})")
    data = resp.json()
    if isinstance(data, dict):
        data = data.get("cameras") or data.get("items") or []
    return [item for item in data if isinstance(item, dict)]


async def fetch_camera_catalogue_isolated() -> list[dict]:
    """Catalogue fetch on a PRIVATE client + loop.

    For callers that run us via asyncio.run() in a worker thread (federation
    sync): the shared module-level client is bound to the app's event loop
    and closing it there poisons the running app (RuntimeError: Event loop
    is closed). Same auth contract, isolated transport.
    """
    import httpx as _httpx

    base = base_url()
    headers = {**_BROWSER_HEADERS, "Referer": base + "/"}
    async with _httpx.AsyncClient(base_url=base, timeout=15.0, follow_redirects=True, headers=headers) as client:
        resp = await client.post(
            _LOGIN_PATH,
            data={"email": settings.grid_email, "password": settings.grid_password},
        )
        if resp.status_code == 403 and any(m in resp.text.lower() for m in _COOLDOWN_MARKERS):
            raise GridAuthError("grid watch-time quota exhausted", code="GRID_COOLDOWN")
        if resp.status_code != 200 or len(client.cookies) == 0:
            raise GridAuthError(f"grid login failed (HTTP {resp.status_code})")
        resp = await client.get("/cameras.json")
        if resp.status_code != 200:
            raise GridAuthError(f"catalogue fetch failed (HTTP {resp.status_code})")
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("cameras") or data.get("items") or []
        return [item for item in data if isinstance(item, dict)]


def grid_unavailable() -> bool:
    """True when login is throttled/quota-drained (live tiles and probes back off)."""
    return in_cooldown()
