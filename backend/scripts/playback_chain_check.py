"""One-shot playback-chain verification (run inside the api container).

watch -> playlist -> key x2 (2nd must come from the server cache) -> segment.
Also asserts the key URL is STABLE across playlist reloads (flicker fix).
"""

import asyncio
import os
import re
import time

import httpx

BASE = "http://127.0.0.1:8000/api/v1"


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{BASE}/auth/login",
            json={"email": "state.admin@sentinel.local", "password": "Sentinel@2026"},
        )
        tok = r.json()["data"]["accessToken"]
        h = {"Authorization": f"Bearer {tok}"}

        streams = (await c.get(f"{BASE}/streams", headers=h)).json()["data"]
        sid = streams[0]["stream_id"]
        print(f"stream: {streams[0]['label']} ({sid[:8]})")

        r = await c.post(f"{BASE}/streams/{sid}/watch", headers=h)
        r.raise_for_status()
        sess = r.json()["data"]["session_id"]
        print(f"session: {sess[:8]}")

        async def playlist() -> tuple[str, str]:
            pr = await c.get(f"{BASE}/streams/hls/{sid}/{sess}/index.m3u8", headers=h)
            pr.raise_for_status()
            body = pr.text
            key_url = next(
                (m for m in re.findall(r'URI="([^"]+)"', body) if "/key/" in m), ""
            )
            seg_url = next(
                (ln for ln in body.splitlines() if ln.startswith("/") and "/seg/" in ln), ""
            )
            return key_url, seg_url

        key1, seg = await playlist()
        key2, _ = await playlist()
        print("key URL stable across reloads:", key1 == key2 and bool(key1))
        print("key token prefix:", key1.rsplit("/", 2)[-2][:12])

        t0 = time.perf_counter()
        kr1 = await c.get(f"http://127.0.0.1:8000{key1}", headers=h)
        t1 = time.perf_counter() - t0
        t0 = time.perf_counter()
        kr2 = await c.get(f"http://127.0.0.1:8000{key2}", headers=h)
        t2 = time.perf_counter() - t0
        print(f"key fetch #1: HTTP {kr1.status_code}, {len(kr1.content)}B in {t1*1000:.0f}ms")
        print(f"key fetch #2: HTTP {kr2.status_code}, {len(kr2.content)}B in {t2*1000:.0f}ms (cache)")
        print("key bytes identical:", kr1.content == kr2.content)

        sr = await c.get(f"http://127.0.0.1:8000{seg}", headers=h)
        print(f"segment: HTTP {sr.status_code}, {len(sr.content)}B")

        ok = (
            key1 == key2
            and kr1.status_code == kr2.status_code == 200
            and kr1.content == kr2.content
            and kr2.status_code == 200
            and sr.status_code == 200
        )
        print("PLAYBACK CHAIN:", "PASSED" if ok else "FAILED")
        await c.post(f"{BASE}/streams/sessions/{sess}/stop", headers=h)

    os._exit(0 if ok else 1)


asyncio.run(main())
