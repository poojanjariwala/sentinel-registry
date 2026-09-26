# Sentinel Registry — Modules 1 & 2

Gujarat Police Innovation Challenge 2026 (CCTV Integration Hackathon).

- **Module 1 — Centralised CCTV Registry & GIS Mapping**: onboarding (manual/bulk/API),
  inventory, GIS mapping, health/maintenance monitoring, gap analysis, department-wise
  RBAC and audit trails.
- **Module 2 — Unified Viewing Platform**: multi-VMS live viewing through an HLS
  gateway with signed segments, viewer sessions, stream health probing, simulated
  ANPR metadata generation, event tagging, searchable vehicle-movement records,
  watchlist alerts, and configurable video walls. Departmental VMS/storage stay
  independent — no central video storage (see docs/ADR-005, ADR-006).

Demo streams come from a bundled ffmpeg media generator (three scenes) exposed
through two simulated VMS systems; the Sentinel sandbox adapter can replace them
via `SENTINEL_API_BASE` without code changes. Real feeds from the Gujarat Police
Sentinel Camera Grid are onboarded with one sync — see below.

## Real Gujarat Police feeds (Sentinel Camera Grid)

The platform runs 100% on the 30 real police cameras alongside the demo scenes:

1. Put the grid access credentials (approved access-list email + access password)
   in `.env`:

   ```
   GRID_BASE_URL=https://cctv.corp8.cloud
   GRID_EMAIL=<approved email>
   GRID_PASSWORD=XXXX-XXXX-XXXX
   ```

2. `docker compose up -d --build api` (migration 0003 adds `stream_sources.auth_json`).
3. Sync the catalogue (idempotent; re-run any time the grid set changes):

   ```bash
   TOKEN=$(curl -s -X POST http://localhost:18000/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"state.admin@sentinel.local","password":"Sentinel@2026"}' \
     | python -c "import sys,json;print(json.load(sys.stdin)['data']['accessToken'])")
   curl -X POST http://localhost:18000/api/v1/streams/admin/sync-grid \
     -H "Authorization: Bearer $TOKEN"
   ```

   This upserts 30 cameras (`GP-CAM01`…, Police department, district inferred from
   the catalogue name) plus HLS stream sources marked VMS `GP-GRID`. Entries that
   disappear from the catalogue are disabled, never deleted. Real URLs are never
   rewritten by the SIM self-heal.

4. Open **Live View** — only the 30 real `GP-GRID` cameras appear. Tiles are
   **click-to-start**: press **Start live** (or a tile's **Play this camera**)
   to open feeds, mirroring the grid portal's own click-to-play model. The
   demo media generator is off by default (`docker compose --profile demo up -d
   mediagen` re-enables it; streams re-seed via `POST /streams/admin/seed-simulated`).

Credentials stay server-side in the api container; browsers only ever receive
signed gateway URLs (docs/ADR-005, ADR-007). The simulated ANPR engine runs only
on SIM streams — no fabricated analytics on real feeds.

5. **Watch-time quota**: the grid limits per-account watch time. Keep the
   original portal tab closed while Sentinel runs — every client draws from
   the same account quota. The platform is click-to-start, probes grid cameras
   round-robin (≈ each camera every ~11 min), and backs off automatically if
   the quota is exhausted (`GRID_COOLDOWN`). Verify real playback any time with:

   ```bash
   docker compose exec api python scripts/grid_probe_check.py cam01
   ```

## Stack

- Backend: Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic
- Database: PostgreSQL 16 + PostGIS (geometry Point/4326, GiST indexes)
- Frontend: React 18 · TypeScript · Vite · Tailwind · MapLibre GL
- Coverage analysis: H3 hexagonal grid (Uber H3)
- Auth: JWT + role/department-scoped RBAC

## Quick start (Docker)

```bash
cp .env.example .env          # adjust ports/secrets if needed
docker compose up --build     # db + api (migrate + seed) + web
# Web:        http://localhost:15173
# API docs:   http://localhost:18000/docs
```

## Quick start (local dev)

```bash
# 1. Database (or use any PostGIS 3.4 instance)
docker compose up -d db

# 2. Backend
cd backend
python -m venv .venv && .venv/Scripts/pip install -e .[dev]   # Linux: .venv/bin/pip
cp ../.env .env
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --port 18000

# 3. Frontend
cd ../frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api to :18000)
```

## Demo accounts (development only)

| Email | Role | Scope |
|---|---|---|
| `state.admin@sentinel.local` | STATE_ADMIN | All departments |
| `dept.admin@sentinel.local` | DEPARTMENT_ADMIN | Police |
| `police.op@sentinel.local` | OPERATOR | Police |
| `muni.op@sentinel.local` | OPERATOR | Municipal |
| `auditor@sentinel.local` | AUDITOR | Audit log only |

Password for all: `Sentinel@2026`

## Demo walkthrough (3 minutes)

1. Login as `state.admin@sentinel.local` → **Live View**: 3×3 video wall playing from two
   simulated VMS systems (GUJCAMS-SIM / CITYCORE-SIM), health strip ONLINE, layout switcher.
2. Click a tile → focus drawer (VMS, department, latency, analytics flag). Switch 2×2 / 1+5.
3. **Vehicle Intelligence**: search `GJ01AB1234` → sightings table (watchlist plate, seeded
   to generate traffic); watchlist panel; live tagged events; **Alerts** with Acknowledge/Close.
4. **GIS Map**: 700+ cameras across 10 districts, colored by department.
5. **Camera Registry**: search/filter; open a camera → edit maintenance/AMC fields → View live.
6. **Onboarding → Bulk import**: `docs/demo_import.csv` → dry-run report → commit (idempotent).
7. **Gap Analysis**: hex coverage + district pivot + ageing list → export CSV.
8. **Audit Trail**: STREAM_WATCH_START/STOP, ALERT_ACK/CLOSE, WATCHLIST_ADD/REMOVE,
   CAMERA_*, SENTINEL_SYNC, GRID_SYNC — all with actor/IP/request-id/before-after.
9. Login as `police.op@sentinel.local` → streams, vehicles and alerts scoped to Police only.

## Deliverables mapping (problem statement)

| Required | Where |
|---|---|
| Working registry portal with GIS map | `frontend` (GIS Map, Registry, detail screens) |
| Bulk + manual onboarding demo | Onboarding screen + `docs/demo_import.csv` |
| Sample camera-metadata dataset | `scripts/seed.py` (7 departments, 30 sites, 490 cameras) |
| Registry API documentation | `/docs` (OpenAPI) + `docs/API.md` |
| Sample gap-analysis report | `docs/sample-gap-report.json` + CSV export endpoint |

## Verified acceptance criteria

- AC-1 Clean DB → `alembic upgrade head` → seed → portal works from documented commands
- AC-2 Manual camera create with full validation; appears on the map immediately
- AC-3 Dry-run flags bad rows with reasons; commit upserts idempotently by `camera_code`
- AC-4 Department-scoped users see only their department in list/map/search/export/import
- AC-5 Every CUD action, import, export and login produces an audit record
- AC-6 Gap analysis produces coverage stats + district pivot + downloadable report
- AC-7 OpenAPI renders all endpoints; README reproduces the demo end-to-end

## Project layout

```
sentinel-registry/
  backend/
    app/{api,core,models,schemas,services}
    migrations/versions/0001_initial.py
    scripts/{seed.py,seed_data.py}
    tests/test_validation.py
  frontend/src/{pages,lib}
  docs/{API.md, ADR-*.md, sample-gap-report.json, demo_import.csv}
  docker-compose.yml
```

## Ports

Local ports default to 15433 (db), 18000 (api), 15173 (web) to avoid clashes with
commonly-used 5432/8000/5173. Adjust in `.env` / `docker-compose.yml`.
