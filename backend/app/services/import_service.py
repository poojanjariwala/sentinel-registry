"""Bulk camera import: CSV/XLSX parsing."""

import csv
import io

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import SentinelError
from app.models.camera import Camera
from app.services.camera_service import site_lookup_map, wkt_point
from app.services.validation import MAX_IMPORT_ROWS, parse_date

IMPORT_COLUMNS = [
    "camera_code", "name", "department_id", "site_id", "camera_type", "ownership",
    "public_facing", "vendor", "model", "ip_address", "latitude", "longitude",
    "district", "taluka", "address", "connectivity_status", "storage_type",
    "retention_days", "install_date", "amc_vendor", "amc_end_date",
    "maintenance_status", "status", "coverage_radius_m",
]

REQUIRED_COLUMNS = {"camera_code", "name", "department_id", "latitude", "longitude"}

CSV_TEMPLATE_HEADER = ",".join(IMPORT_COLUMNS)


def parse_rows(data: bytes, filename: str) -> list[dict]:
    """Parse CSV or XLSX bytes into normalized dict rows."""
    name_lower = (filename or "").lower()
    rows: list[dict] = []
    if name_lower.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        try:
            header = [str(h).strip().lower().replace(" ", "_") if h is not None else "" for h in next(it)]
        except StopIteration:
            raise SentinelError("IMPORT_EMPTY", "File has no header row", 400)
        for r_idx, raw in enumerate(it, start=2):
            if all(v is None or str(v).strip() == "" for v in raw):
                continue
            row = {h: raw[i] for i, h in enumerate(header) if h}
            row["__row"] = r_idx
            rows.append(row)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        reader = csv.reader(io.StringIO(text))
        try:
            header = [h.strip().lower().replace(" ", "_") for h in next(reader)]
        except StopIteration:
            raise SentinelError("IMPORT_EMPTY", "File has no header row", 400)
        for r_idx, raw in enumerate(reader, start=2):
            if not raw or all(str(v).strip() == "" for v in raw):
                continue
            row = {h: (raw[i] if i < len(raw) else None) for i, h in enumerate(header)}
            row["__row"] = r_idx
            rows.append(row)
    if not rows:
        raise SentinelError("IMPORT_EMPTY", "No data rows found in file", 400)
    if len(rows) > MAX_IMPORT_ROWS:
        raise SentinelError("IMPORT_TOO_LARGE", f"More than {MAX_IMPORT_ROWS} data rows", 400)
    missing = REQUIRED_COLUMNS - set(header)
    if missing:
        raise SentinelError(
            "IMPORT_MISSING_COLUMNS",
            f"Missing required columns: {', '.join(sorted(missing))}",
            400,
        )
    return rows


def _department_map(db: Session) -> dict[str, str]:
    """Map department code/name/uuid (uppercased) -> department UUID."""
    from app.models.department import Department

    m: dict[str, str] = {}
    for d in db.execute(select(Department)).scalars().all():
        m[d.code.upper()] = d.department_id
        m[d.name.upper()] = d.department_id
        m[d.department_id] = d.department_id
    return m


def _fallback_department(db: Session, department_scope: list[str] | None) -> str:
    """Department used when a CSV's department cannot be resolved.

    Scoped operators import into their own first department; state-wide users
    get/reuse an UNASSIGNED catch-all department so nothing is silently dropped.
    """
    from app.models.department import Department

    if department_scope:
        return department_scope[0]
    existing = db.execute(
        select(Department).where(Department.code == "UNASSIGNED")
    ).scalar_one_or_none()
    if existing:
        return existing.department_id
    dept = Department(name="Unassigned Imports", code="UNASSIGNED",
                      description="Auto-created for imports with unresolvable department references")
    db.add(dept)
    db.flush()
    return dept.department_id


def upsert_rows(db: Session, rows: list[dict], department_scope: list[str] | None, dry_run: bool = False) -> dict:
    """Validate and upsert rows keyed on camera_code; returns a report dict.

    With dry_run=True no writes are performed; counts reflect what would change.
    """
    from app.services.validation import validate_camera_row

    report_rows = []
    warning_rows = []
    valid_rows = []
    for row in rows:
        row_warnings: list[str] = []
        if "__warnings" in row:
            row_warnings = row.pop("__warnings")
        errors = validate_camera_row(row)
        if errors:
            report_rows.append({"row": row.get("__row"), "errors": errors})
            continue
        if row_warnings:
            warning_rows.append({"row": row.get("__row"), "warnings": row_warnings})
        valid_rows.append(row)

    # Resolve department codes/names to UUIDs and enforce operator scope.
    depmap = _department_map(db)
    sitecap = site_lookup_map(db)
    scope_set = set(department_scope) if department_scope is not None else None
    fallback_dept = _fallback_department(db, department_scope)
    scoped: list[dict] = []
    for row in valid_rows:
        raw = str(row.get("department_id") or "").strip()
        resolved = depmap.get(raw.upper())
        if resolved and scope_set is not None and resolved not in scope_set:
            resolved = None  # treat out-of-scope as unresolvable for this operator
        if not resolved:
            # Any-CSV policy: never drop the row. Import under a safe department
            # and surface a warning so an admin can reassign later.
            row_warnings = row.setdefault("__warnings", [])
            row_warnings.append(
                f"department '{raw or 'blank'}' not recognized - imported under "
                f"'UNASSIGNED' catch-all for later reassignment"
                if not department_scope else
                f"department '{raw or 'blank'}' outside your scope - imported under your department"
            )
            resolved = fallback_dept
        row["department_id"] = resolved

        site_raw = str(row.get("site_id") or "").strip()
        if site_raw:
            site_uuid = sitecap.get(site_raw.upper())
            if site_uuid:
                row["site_id"] = site_uuid
            else:
                # Unknown site reference: import with the site unlinked, surface a warning.
                row["site_id"] = None
                warning_rows.append({
                    "row": row.get("__row"),
                    "warnings": [f"site_id '{site_raw}' not found in registry - camera imported without site link"],
                })
        else:
            row["site_id"] = None

        scoped.append(row)

    created = updated = 0
    pending_codes: set[str] = set()
    for row in scoped:
        code = str(row["camera_code"]).strip()
        existing = db.execute(
            select(Camera).where(Camera.camera_code == code)
        ).scalar_one_or_none()
        if existing is None and code in pending_codes:
            # Same camera_code appears twice in this file (create path).
            report_rows.append({
                "row": row.get("__row"),
                "errors": [f"duplicate camera_code '{code}' within file"],
            })
            continue
        pending_codes.add(code)
        data = {
            "name": str(row["name"]).strip(),
            "department_id": str(row["department_id"]).strip(),
            "site_id": (str(row.get("site_id")).strip() or None) if row.get("site_id") else None,
            "camera_type": (row.get("camera_type") or "FIXED"),
            "ownership": (row.get("ownership") or "GOVERNMENT"),
            "public_facing": str(row.get("public_facing", "")).strip().lower() in {"true", "1", "yes", "y"},
            "vendor": row.get("vendor"),
            "model": row.get("model"),
            "ip_address": row.get("ip_address"),
            "latitude": row.get("latitude"),
            "longitude": row.get("longitude"),
            "district": row.get("district"),
            "taluka": row.get("taluka"),
            "address": row.get("address"),
            "connectivity_status": (row.get("connectivity_status") or "UNKNOWN"),
            "storage_type": (row.get("storage_type") or None),
            "retention_days": row.get("retention_days"),
            "install_date": row.get("install_date"),
            "amc_vendor": row.get("amc_vendor"),
            "amc_end_date": row.get("amc_end_date"),
            "maintenance_status": (row.get("maintenance_status") or "OK"),
            "status": (row.get("status") or "ACTIVE"),
            "coverage_radius_m": row.get("coverage_radius_m"),
        }
        data["location"] = wkt_point(row.get("longitude"), row.get("latitude"))

        # Empty CSV cells must become NULL, not '' (Postgres date/int columns reject '').
        for k, v in list(data.items()):
            if v == "":
                data[k] = None
        for k in ("install_date", "amc_end_date"):
            if data[k] is not None and not isinstance(data[k], date):
                data[k] = parse_date(data[k])

        if existing:
            if not dry_run:
                for k, v in data.items():
                    setattr(existing, k, v)
            updated += 1
        else:
            if not dry_run:
                db.add(Camera(camera_code=code, **data))
            created += 1

    return {
        "rows": report_rows,
        "warnings": warning_rows,
        "created": created,
        "updated": updated,
        "errors": len(report_rows),
        "warning_count": len(warning_rows),
    }
