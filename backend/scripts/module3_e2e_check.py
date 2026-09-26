"""End-to-end Module 3 verification (run inside the api container).

Covers:
- AC-01: a second, heterogeneous VMS (generic_hls manifest adapter) is
  registered, discovered, and its cameras/streams land in the registry.
- AC-11: a dead adapter (unreachable manifest) fails ISOLATED - discover-all
  still returns, the platform keeps working, and other VMS results are intact.
- Registry invariants: enable/disable pull-through, audit of failures.
"""

import json
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
ok = True


def check(name: str, cond: bool, extra: str = "") -> None:
    global ok
    print(f"{'PASS' if cond else 'FAIL'}: {name}" + (f" - {extra}" if extra else ""))
    ok = ok and cond


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        f"{BASE}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def main() -> None:
    _, login = call("POST", "/auth/login", body={"email": "state.admin@sentinel.local", "password": "Sentinel@2026"})
    tok = login["data"]["accessToken"]

    # 1. Register a REAL second VMS (heterogeneous: plain HTTP manifest, no grid auth)
    st, created = call("POST", "/vms", tok, {
        "name": "CITY-VMS-B", "vendor": "Vendor B (manifest)", "adapter_kind": "generic_hls",
        "base_url": "http://127.0.0.1:8899/cameras.json",
    })
    check("register VMS-B", st == 200, f"HTTP {st}")
    vms_b = created["data"]["vms_id"]

    # 2. Discover from it -> cameras + streams land in the registry
    # (idempotency-aware: count final registry state, not creation deltas,
    # so the check holds on re-runs against an already-discovered source)
    st, disc = call("POST", f"/vms/{vms_b}/discover", tok)
    d = disc["data"]
    check("discover VMS-B", st == 200 and d["ok"], json.dumps({k: d.get(k) for k in ("cameras_created", "streams_created")}))
    st, streams = call("GET", "/streams?page=1&pageSize=100", tok)
    rows = streams["data"] if isinstance(streams["data"], list) else streams["data"].get("items", [])
    b_enabled = [r for r in rows if r["vms_system"] == "CITY-VMS-B" and r["enabled"]]
    check("VMS-B feeds live in registry (>=2)", len(b_enabled) >= 2, f"enabled={len(b_enabled)}")

    # 3. Dead adapter: isolation test (AC-11)
    st, dead = call("POST", "/vms", tok, {
        "name": "DEAD-VMS", "vendor": "Unreachable", "adapter_kind": "generic_hls",
        "base_url": "http://127.0.0.1:59999/cameras.json",
    })
    dead_id = dead["data"]["vms_id"]
    st, allres = call("POST", "/vms/discover-all", tok)
    results = allres["data"]["results"]
    dead_res = next((r for r in results if r["vms"] == "DEAD-VMS"), None)
    grid_res = next((r for r in results if r["vms"] == "GP-GRID"), None)
    b_res = next((r for r in results if r["vms"] == "CITY-VMS-B"), None)
    check("discover-all completes despite dead adapter", st == 200 and len(results) >= 3)
    check("dead adapter reports OFFLINE, not crash", dead_res is not None and dead_res["ok"] is False)
    check("grid + VMS-B results unaffected", b_res is not None and b_res["ok"] is True and grid_res is not None)

    st, health = call("GET", "/health/ready")
    check("platform healthy after adapter failure", st == 200)

    # 4. Disable VMS-B -> its streams must leave the wall
    st, _ = call("PATCH", f"/vms/{vms_b}", tok, {"enabled": False})
    st, streams = call("GET", "/streams?page=1&pageSize=100", tok)
    rows = streams["data"] if isinstance(streams["data"], list) else streams["data"].get("items", [])
    check("disable VMS-B pulls its streams", all(r["enabled"] is False for r in rows if r["vms_system"] == "CITY-VMS-B"))
    # 5. Re-enable + re-discover restores them (idempotent upsert)
    call("PATCH", f"/vms/{vms_b}", tok, {"enabled": True})
    st, redisc = call("POST", f"/vms/{vms_b}/discover", tok)
    st, streams = call("GET", "/streams?page=1&pageSize=100", tok)
    rows = streams["data"] if isinstance(streams["data"], list) else streams["data"].get("items", [])
    b_back = [r for r in rows if r["vms_system"] == "CITY-VMS-B" and r["enabled"]]
    check("re-discover restores VMS-B streams", st == 200 and redisc["data"]["ok"] and len(b_back) >= 2, f"enabled={len(b_back)}")

    # 6. Cleanup: unregister the demo VMS (its streams must be pulled too)
    for vid in (vms_b, dead_id):
        call("DELETE", f"/vms/{vid}", tok)
    st, after = call("GET", "/vms", tok)
    names = [v["name"] for v in after["data"]]
    check("cleanup deletes demo VMS", "CITY-VMS-B" not in names and "DEAD-VMS" not in names, f"remaining={names}")
    st, streams = call("GET", "/streams?page=1&pageSize=100", tok)
    rows = streams["data"] if isinstance(streams["data"], list) else streams["data"].get("items", [])
    check("unregistered VMS leaves no enabled feeds", all(r["enabled"] is False for r in rows if r["vms_system"] in ("CITY-VMS-B", "DEAD-VMS")))

    # 7. Test-fixture teardown: purge demo rows (this is a TEST script; the
    # platform's own sync paths only ever disable - deletion happens here so
    # repeated runs stay idempotent and the registry keeps zero demo residue).
    from app.core.db import SessionLocal
    from sqlalchemy import delete as _del
    from sqlalchemy import select as _sel

    from app.models.camera import Camera as _Cam
    from app.models.module2 import (
        StreamHealthEvent as _She,
        StreamSource as _SS,
        TaggedEvent as _Te,
        VehicleObservation as _Vo,
        ViewerSession as _Vs,
    )

    with SessionLocal() as db:
        demo_streams = db.execute(
            _sel(_SS.stream_id).where(_SS.vms_system.in_(["CITY-VMS-B", "DEAD-VMS"]))
        ).scalars().all()
        demo_cams = db.execute(
            _sel(_Cam.camera_id).where(_Cam.camera_code.like("DEMO-VMS-B-%"))
        ).scalars().all()
        n_h = db.execute(_del(_She).where(_She.stream_id.in_(demo_streams))).rowcount if demo_streams else 0
        n_v = db.execute(_del(_Vs).where(_Vs.stream_id.in_(demo_streams))).rowcount if demo_streams else 0
        n_t = db.execute(_del(_Te).where(_Te.camera_id.in_(demo_cams))).rowcount if demo_cams else 0
        n_o = db.execute(_del(_Vo).where(_Vo.camera_id.in_(demo_cams))).rowcount if demo_cams else 0
        n_s = db.execute(_del(_SS).where(_SS.vms_system.in_(["CITY-VMS-B", "DEAD-VMS"]))).rowcount
        n_c = db.execute(_del(_Cam).where(_Cam.camera_code.like("DEMO-VMS-B-%"))).rowcount
        db.commit()
    print(f"teardown: removed {n_s} streams (+{n_h} health, {n_v} sessions, {n_t} events, {n_o} obs), {n_c} cameras")

    print("\nMODULE 3 E2E:", "PASSED" if ok else "FAILED")
    raise SystemExit(0 if ok else 1)


main()
