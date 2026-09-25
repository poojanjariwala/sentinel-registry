"""Camera registry endpoints: CRUD, bulk import, CSV export."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import client_ip, require_perm
from app.core.errors import SentinelError, request_id_var
from app.models.camera import Camera
from app.models.department import Department
from app.models.import_batch import CameraImportBatch
from app.models.user import Role, UserRole
from app.services import audit as audit_svc
from app.services.camera_service import (
    get_camera_scoped,
    query_cameras,
    resolve_site,
    to_dict,
    user_department_filter,
    wkt_point,
)
from app.services.export_service import cameras_csv
from app.services.import_service import CSV_TEMPLATE_HEADER, parse_rows, upsert_rows
from app.services.validation import parse_date, validate_camera_row

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _envelope(data, meta: dict | None = None) -> dict:
    return {"data": data, "meta": meta or {}, "requestId": request_id_var.get()}


def _audit_value(cam: Camera) -> dict:
    return {
        "camera_code": cam.camera_code, "name": cam.name,
        "department_id": cam.department_id, "latitude": cam.latitude,
        "longitude": cam.longitude, "status": cam.status,
        "maintenance_status": cam.maintenance_status,
    }


def _ensure_department_in_scope(department_id: str, user, db: Session) -> None:
    flt = user_department_filter(user, db)
    if flt is None:
        return
    dept = db.get(Department, department_id)
    if not dept:
        raise SentinelError("DEPARTMENT_NOT_FOUND", "Department not found", 404)
    if department_id not in user_department_ids(user, db):
        raise SentinelError("AUTH_FORBIDDEN", "Department outside your scope", 403)


def user_department_ids(user, db: Session) -> list[str] | None:
    """Scoped department ids for the user; None means state-wide."""
    role_names = db.execute(
        select(Role.name).join(UserRole, UserRole.role_name == Role.name).where(UserRole.user_id == user.user_id)
    ).scalars().all()
    if any(r in {"STATE_ADMIN", "AUDITOR"} for r in role_names):
        return None
    return [
        row[0]
        for row in db.execute(select(UserRole.department_id).where(UserRole.user_id == user.user_id)).all()
        if row[0]
    ]


@router.get("")
def list_cameras(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    department_id: str | None = None,
    district: str | None = None,
    camera_type: str | None = None,
    status: str | None = None,
    connectivity: str | None = None,
    maintenance: str | None = None,
    storage: str | None = None,
    search: str | None = None,
    bbox: str | None = None,
    sort: str = "-updated_at",
    user=Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    rows, total = query_cameras(
        db, user, page, page_size, department_id, district, camera_type,
        status, connectivity, maintenance, storage, search, bbox, sort,
    )
    return _envelope([to_dict(c) for c in rows], {"page": page, "pageSize": page_size, "total": total})


@router.get("/export.csv")
def export_csv(
    request: Request,
    department_id: str | None = None,
    district: str | None = None,
    camera_type: str | None = None,
    status: str | None = None,
    connectivity: str | None = None,
    maintenance: str | None = None,
    storage: str | None = None,
    search: str | None = None,
    bbox: str | None = None,
    user=Depends(require_perm("camera", "export")),
    db: Session = Depends(get_db),
):
    audit_svc.record(
        db, "CAMERA_EXPORT", "camera_set", None,
        after_state={"filters": {k: v for k, v in {
            "department_id": department_id, "district": district, "camera_type": camera_type,
            "status": status, "connectivity": connectivity, "maintenance": maintenance,
            "storage": storage, "search": search, "bbox": bbox,
        }.items() if v}},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    content, count = cameras_csv(db, user, department_id=department_id, district=district,
                                 camera_type=camera_type, status=status, connectivity=connectivity,
                                 maintenance=maintenance, storage=storage, search=search, bbox=bbox)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="cameras_export.csv"'},
    )


@router.get("/import-template.csv")
def import_template():
    return Response(
        content=(CSV_TEMPLATE_HEADER + "\n").encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="camera_import_template.csv"'},
    )


@router.post("/import")
async def import_cameras(
    request: Request,
    file: UploadFile,
    dry_run: bool = False,
    user=Depends(require_perm("camera", "import")),
    db: Session = Depends(get_db),
):
    data = await file.read()
    if not data:
        raise SentinelError("IMPORT_EMPTY", "Uploaded file is empty", 400)
    rows = parse_rows(data, file.filename or "upload.csv")

    scope = user_department_ids(user, db)
    report = upsert_rows(db, rows, scope, dry_run=dry_run)

    batch = CameraImportBatch(
        filename=file.filename or "upload.csv",
        uploaded_by=user.user_id,
        dry_run=dry_run,
        status="DRY_RUN" if dry_run else "COMPLETED",
        total_rows=len(rows),
        created_count=report["created"],
        updated_count=report["updated"],
        error_count=report["errors"],
        report_json={"rows": report["rows"][:500], "warnings": report["warnings"][:500]},
        completed_at=datetime.now(timezone.utc),
    )
    db.add(batch)

    audit_svc.record(
        db, "CAMERA_IMPORT", "import_batch", None,
        after_state={"filename": batch.filename, "dry_run": dry_run,
                     "total": len(rows), "created": report["created"],
                     "updated": report["updated"], "errors": report["errors"],
                     "warnings": report["warning_count"]},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    return _envelope({
        "batch_id": batch.batch_id, "dry_run": dry_run, "filename": batch.filename,
        "total_rows": batch.total_rows, "created": batch.created_count,
        "updated": batch.updated_count, "errors": batch.error_count,
        "warning_count": report["warning_count"],
        "report": report,
    })


@router.get("/imports")
def list_imports(
    user=Depends(require_perm("camera", "import")),
    db: Session = Depends(get_db),
):
    batches = db.execute(
        select(CameraImportBatch).order_by(CameraImportBatch.created_at.desc()).limit(50)
    ).scalars().all()
    return _envelope([
        {
            "batch_id": b.batch_id, "filename": b.filename, "dry_run": b.dry_run,
            "status": b.status, "total_rows": b.total_rows, "created": b.created_count,
            "updated": b.updated_count, "errors": b.error_count,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        }
        for b in batches
    ])


@router.post("")
def create_camera(
    body: dict,
    request: Request,
    user=Depends(require_perm("camera", "write")),
    db: Session = Depends(get_db),
):
    row = {
        "camera_code": body.get("camera_code"),
        "name": body.get("name"),
        "department_id": body.get("department_id"),
        "latitude": body.get("latitude"),
        "longitude": body.get("longitude"),
        "camera_type": body.get("camera_type"),
        "ownership": body.get("ownership"),
        "storage_type": body.get("storage_type"),
        "connectivity_status": body.get("connectivity_status"),
        "maintenance_status": body.get("maintenance_status"),
        "status": body.get("status"),
        "retention_days": body.get("retention_days"),
        "coverage_radius_m": body.get("coverage_radius_m"),
    }
    errors = validate_camera_row(row)
    if errors:
        raise SentinelError("VALIDATION_ERROR", "Camera validation failed", 422, {"errors": errors})

    if db.execute(select(Camera).where(Camera.camera_code == str(body["camera_code"]).strip())).scalar_one_or_none():
        raise SentinelError("CAMERA_CODE_EXISTS", "A camera with this camera_code already exists", 409)

    _ensure_department_in_scope(body["department_id"], user, db)
    site_uuid = resolve_site(db, body.get("site_id"))

    cam = Camera(
        camera_code=str(body["camera_code"]).strip(),
        name=str(body["name"]).strip(),
        department_id=body["department_id"],
        site_id=site_uuid,
        camera_type=row.get("camera_type") or "FIXED",
        ownership=row.get("ownership") or "GOVERNMENT",
        public_facing=bool(body.get("public_facing", False)),
        vendor=body.get("vendor"),
        model=body.get("model"),
        ip_address=body.get("ip_address"),
        latitude=row.get("latitude"),
        longitude=row.get("longitude"),
        location=wkt_point(row.get("longitude"), row.get("latitude")),
        district=body.get("district"),
        taluka=body.get("taluka"),
        address=body.get("address"),
        connectivity_status=row.get("connectivity_status") or "UNKNOWN",
        storage_type=row.get("storage_type"),
        retention_days=row.get("retention_days"),
        install_date=parse_date(body.get("install_date")),
        amc_vendor=body.get("amc_vendor"),
        amc_end_date=parse_date(body.get("amc_end_date")),
        maintenance_status=row.get("maintenance_status") or "OK",
        status=row.get("status") or "ACTIVE",
        coverage_radius_m=row.get("coverage_radius_m"),
        metadata_json=body.get("metadata"),
    )
    db.add(cam)
    db.flush()

    audit_svc.record(
        db, "CAMERA_CREATE", "camera", cam.camera_id,
        after_state=_audit_value(cam),
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(cam)
    return _envelope(to_dict(cam))


@router.get("/{camera_id}")
def get_camera(
    camera_id: str,
    user=Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    cam = get_camera_scoped(camera_id, user, db)
    return _envelope(to_dict(cam))


@router.patch("/{camera_id}")
def update_camera(
    camera_id: str,
    body: dict,
    request: Request,
    user=Depends(require_perm("camera", "write")),
    db: Session = Depends(get_db),
):
    cam = get_camera_scoped(camera_id, user, db)
    before = _audit_value(cam)

    allowed = {
        "name", "camera_type", "ownership", "public_facing", "vendor",
        "model", "ip_address", "latitude", "longitude", "district", "taluka",
        "address", "connectivity_status", "storage_type", "retention_days",
        "install_date", "amc_vendor", "amc_end_date", "maintenance_status",
        "status", "coverage_radius_m", "metadata",
    }
    for k, v in body.items():
        if k not in allowed:
            continue
        if k in ("latitude", "longitude") and v is not None:
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise SentinelError("VALIDATION_ERROR", f"{k} must be a number", 422)
        if k in ("install_date", "amc_end_date"):
            v = parse_date(v)
        if k == "metadata":
            cam.metadata_json = v
        else:
            setattr(cam, k, v)

    if "site_id" in body:
        cam.site_id = resolve_site(db, body.get("site_id"))

    if "latitude" in body or "longitude" in body:
        cam.location = wkt_point(cam.longitude, cam.latitude)

    audit_svc.record(
        db, "CAMERA_UPDATE", "camera", cam.camera_id,
        before_state=before, after_state=_audit_value(cam),
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(cam)
    return _envelope(to_dict(cam))


@router.delete("/{camera_id}")
def delete_camera(
    camera_id: str,
    request: Request,
    user=Depends(require_perm("camera", "delete")),
    db: Session = Depends(get_db),
):
    cam = get_camera_scoped(camera_id, user, db)
    before = _audit_value(cam)
    cam.status = "DECOMMISSIONED"
    audit_svc.record(
        db, "CAMERA_DELETE", "camera", cam.camera_id,
        before_state=before, after_state=_audit_value(cam),
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return _envelope({"ok": True, "camera_id": cam.camera_id, "status": cam.status})
