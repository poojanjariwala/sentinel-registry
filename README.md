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
via `SENTINEL_API_BASE` without code changes.

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
   CAMERA_*, SENTINEL_SYNC — all with actor/IP/request-id/before-after.
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
