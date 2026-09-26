"""Polite grid verification utility.

Waits out a possible watch-time cooldown inside a single process (so we never
send more than one login attempt per backoff window), then performs a MINIMAL
end-to-end check of one real camera through the gateway primitives:
playlist fetch + rewrite, one signed segment, one signed key.

Usage (inside the api container):
    python scripts/grid_probe_check.py [grid_id]   # default cam01
"""

import asyncio
import sys
import time

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.services import grid_client  # noqa: E402
from app.services.hls_service import (  # noqa: E402
    OriginSpec,
    _rewrite_to_rolling_window,
    fetch_key,
    fetch_segment,
)


async def main() -> None:
    grid_id = sys.argv[1] if len(sys.argv) > 1 else "cam01"
    url = grid_client.camera_hls_url(grid_id)

    resp = None
    for attempt in (1, 2):
        try:
            resp = await grid_client.authed_get(url)
            break
        except grid_client.GridAuthError as e:
            msg = str(e).lower()
            if not ("cooldown" in msg or "quota" in msg) or attempt == 2:
                raise
            wait = min(120, grid_client.cooldown_remaining_seconds() or 900)
            print(f"watch-time cooldown; waiting {wait}s before attempt {attempt + 1}...")
            time.sleep(wait + 5)
    if resp is None:
        raise SystemExit("could not fetch grid playlist")
    resp.raise_for_status()
    print(f"playlist fetch: HTTP {resp.status_code}, {len(resp.text)} bytes")

    stream = OriginSpec(
        stream_id="probe-check",
        source_url=url,
        protocol="HLS",
        auth_json=None,
    )
    rewritten = _rewrite_to_rolling_window(stream, resp.text, session_id="probe-check")
    seg_lines = [l for l in rewritten.splitlines() if "/seg/" in l]
    key_lines = [l for l in rewritten.splitlines() if "/key/" in l]
    print(f"rolling window: {len(seg_lines)} signed segment URLs; key proxied: {bool(key_lines)}")
    print("media-sequence:", next(l for l in rewritten.splitlines() if l.startswith("#EXT-X-MEDIA-SEQUENCE")))

    seg_name = seg_lines[0].rsplit("/", 1)[-1]
    data, _h = await fetch_segment(stream, seg_name)
    print(f"segment {seg_name}: {len(data)} bytes via gateway")

    key = await fetch_key(stream, "enc.key")
    print(f"key enc.key: {len(key)} bytes (16 = AES-128 key)")

    print("GRID PLAYBACK CHECK PASSED")


if __name__ == "__main__":
    asyncio.run(main())
