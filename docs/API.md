# Sentinel Registry API

Base URL: `/api/v1` · OpenAPI UI: `/docs` · All responses: `{ data, meta, requestId }`
Errors: `{ error: { code, message, details }, requestId }`

## Authentication

- `POST /auth/login` `{ "email", "password" }` → `{ accessToken, user }`
- Send `Authorization: Bearer <token>` on every other call.
- `GET /auth/me` · `POST /auth/logout`

Roles: `STATE_ADMIN`, `DEPARTMENT_ADMIN`, `OPERATOR`, `AUDITOR`, `VIEWER`.
Department-scoped roles only see cameras inside their granted departments — enforced
in the query layer (list, GIS, export, import), not merely at route level.

## Cameras

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/cameras` | camera.read | Filters: `department_id, district, camera_type, status, connectivity, maintenance, storage, search, bbox=minLng,minLat,maxLng,maxLat, sort` · paging `page,page_size` |
| POST | `/cameras` | camera.write | Full validation incl. Gujarat bbox; 409 on duplicate `camera_code` |
| GET | `/cameras/{id}` | camera.read | 404 unknown · 403 out-of-scope |
| PATCH | `/cameras/{id}` | camera.write | Partial update; audited with before/after |
| DELETE | `/cameras/{id}` | camera.delete | Soft delete → `status=DECOMMISSIONED` |
| GET | `/cameras/export.csv` | camera.export | Same filters; audited |
| POST | `/cameras/import?dry_run=` | camera.import | Multipart `file` (CSV/XLSX ≤5000 rows); returns row-level report |
| GET | `/cameras/imports` | camera.import | Recent import batches |
| GET | `/cameras/import-template.csv` | — | Downloadable column template |

Import accepts `department_id` as department **code** (e.g. `POLICE`), **name**, or UUID —
resolved server-side. Rows referencing departments outside the operator's scope are
rejected in the report, never partially committed. Re-committing a file is idempotent
(upsert keyed on `camera_code`).

## GIS

- `GET /gis/cameras` — camera.read — GeoJSON FeatureCollection; same filters + `bbox`.

## Coverage / gap analysis

- `POST /coverage/gap-analysis` `{ departments?, districts?, resolution(4-10, default 8), min_cameras_per_cell, ageing_years }` — coverage.run
- `GET /coverage/runs` · `GET /coverage/runs/{id}` · `GET /coverage/runs/{id}/export.csv`

## Reference data & admin

- `GET /departments` (any authenticated) · `POST /departments` (dept.manage)
- `GET /users` / `POST /users` (user.manage) · `GET /roles`
- `GET /audit` (audit.read) — filters `action, actor, resource_type`, paged
- `GET /health/live` · `GET /health/ready`

## Module 2 — Unified viewing & analytics

### Streams (unified viewer)

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/streams` | camera.read | Catalog with `q, vms_system, status, department_id` filters; returns VMS options |
| GET | `/streams/health/summary` | camera.read | ONLINE/OFFLINE/UNKNOWN counts |
| POST | `/streams/{id}/watch` | camera.read | Creates viewer session → `{session_id, hls_url}`; audited |
| POST | `/streams/sessions/{id}/heartbeat` | camera.read | Keeps session alive (stale sweep at 2 min) |
| POST | `/streams/sessions/{id}/stop` | camera.read | Ends session; audited |
| GET | `/streams/{id}/health` | camera.read | Status + probe history |
| GET | `/streams/hls/{sid}/{sess}/index.m3u8` | session | Playlist (rewritten, signed segment URLs) |
| GET | `/streams/hls/{sid}/{sess}/{token}/seg/{name}` | signed token | Segment proxy; expired/invalid → 403, rolled-off → 404 |
| POST | `/streams/admin/sync-sentinel` | user.manage | Pull Sentinel `/api/ingest` catalogue into stream_sources |
| POST | `/streams/admin/seed-simulated` | user.manage | Seed demo streams across two VMS systems + demo watchlist |

### Vehicle intelligence / events / watchlist / alerts

- `GET /vehicles/search?plate=&hours=` — exact normalized match, falls back to last-4 partial; department-scoped.
- `GET /vehicles/{plate}/timeline?hours=` — chronological sightings + movement legs with gaps.
- `GET /events?hours=&event_type=&severity=&stream_id=` — camera-wise indexed tagged events; `POST /events` to tag manually.
- `GET/POST /watchlist`, `DELETE /watchlist/{id}` — vehicles of interest (audited).
- `GET /alerts?status=&hours=`, `POST /alerts/{id}/ack`, `POST /alerts/{id}/close` — watchlist-hit alert lifecycle (audited).

Background workers (toggle `ENABLE_MODULE2_WORKERS`): stream health prober (45 s)
and the demo ANPR engine (8 s) that writes observations, tags events and raises
watchlist alerts. Simulated rows carry `engine='simulated'`.

## Audit coverage

`LOGIN_SUCCESS`, `LOGIN_FAILED`, `LOGOUT`, `CAMERA_CREATE`, `CAMERA_UPDATE`,
`CAMERA_DELETE`, `CAMERA_IMPORT`, `CAMERA_EXPORT`, `COVERAGE_RUN_CREATE`,
`DEPARTMENT_CREATE`, `USER_CREATE`. Records include actor, IP, user-agent,
request id and before/after state. Append-only.
