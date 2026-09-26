"""Sentinel Registry API - FastAPI application entrypoint."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import RequestIDMiddleware, install_error_handlers
from app.api import audit, auth, cameras, coverage, federation, gis, meta, streams, vehicles

settings = get_settings()

_stop = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    tasks = []
    if settings.enable_module2_workers:
        from app.services.anpr_worker import anpr_loop
        from app.services.stream_health import health_loop

        tasks = [
            asyncio.create_task(health_loop(stop)),
            asyncio.create_task(anpr_loop(stop)),
        ]
    # Module 3: idempotent federation registry seeding (default adapters).
    try:
        from app.core.db import SessionLocal
        from app.services.federation import ensure_default_registrations

        with SessionLocal() as db:
            ensure_default_registrations(db)
    except Exception:  # noqa: S110 - seed failure must not block boot; admin can re-register
        pass
    yield
    stop.set()
    for t in tasks:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):  # noqa: S110
            pass


app = FastAPI(
    title="Sentinel Registry API",
    description=(
        "Module 1: Centralised CCTV Registry & GIS Mapping · "
        "Module 2: Unified Viewing Platform + selective analytics "
        "(Gujarat Police Innovation Challenge 2026)"
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_error_handlers(app)

API_PREFIX = "/api/v1"

app.include_router(meta.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(cameras.router, prefix=API_PREFIX)
app.include_router(gis.router, prefix=API_PREFIX)
app.include_router(coverage.router, prefix=API_PREFIX)
app.include_router(audit.router, prefix=API_PREFIX)
app.include_router(streams.router, prefix=API_PREFIX)
app.include_router(vehicles.router, prefix=API_PREFIX)
app.include_router(federation.router, prefix=API_PREFIX)


@app.get("/")
def root():
    return {
        "service": "sentinel-registry",
        "modules": [
            "M1 - Centralised CCTV Registry & GIS Mapping",
            "M2 - Unified Viewing Platform (streams, ANPR metadata, events, watchlist, alerts, walls)",
            "M3 - VMS Federation & Middleware (adapter registry, discovery, health)",
        ],
        "docs": "/docs",
        "health": "/api/v1/health/live",
    }
