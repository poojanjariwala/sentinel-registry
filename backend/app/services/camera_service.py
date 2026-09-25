"""Camera query service with department scoping and filtering."""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import SentinelError
from app.models.camera import Camera
from app.models.department import Department, Site
from app.models.user import Role, UserRole


def wkt_point(lng, lat):
    """EWKT string for PostGIS location column, or None if coords missing."""
    if lat is None or lng is None:
        return None
    return f"SRID=4326;POINT({float(lng)} {float(lat)})"


def site_lookup_map(db: Session) -> dict[str, str]:
    """Map site UUID and uppercase site name -> site UUID (for import/manual entry)."""
    m: dict[str, str] = {}
    for s in db.execute(select(Site)).scalars().all():
        m[s.site_id] = s.site_id
        m[s.name.upper()] = s.site_id
    return m


def resolve_site(db: Session, raw: str | None) -> str | None:
    """Resolve a site by UUID or exact name; raises 404-style error if unknown."""
    if raw is None or str(raw).strip() == "":
        return None
    site = site_lookup_map(db).get(str(raw).strip().upper())
    if not site:
        raise SentinelError("SITE_NOT_FOUND", f"Site '{raw}' not found in registry", 422)
    return site


def user_department_filter(user, db: Session):
    """Return a SQLAlchemy filter restricting cameras to the user's scope, or None.

    None means unrestricted (state-wide roles: STATE_ADMIN, AUDITOR).
    """
    role_names = db.execute(
        select(Role.name).join(UserRole, UserRole.role_name == Role.name).where(UserRole.user_id == user.user_id)
    ).scalars().all()
    if any(r in {"STATE_ADMIN", "AUDITOR"} for r in role_names):
        return None
    dept_ids = [
        row[0]
        for row in db.execute(
            select(UserRole.department_id).where(UserRole.user_id == user.user_id)
        ).all()
        if row[0]
    ]
    if not dept_ids:
        # Users with roles but no department scope see nothing.
        return Camera.department_id.in_(["__none__"])
    return Camera.department_id.in_(dept_ids)


def get_camera_scoped(camera_id: str, user, db: Session) -> Camera:
    cam = db.get(Camera, camera_id)
    if not cam:
        raise SentinelError("CAMERA_NOT_FOUND", "Camera not found", 404)
    flt = user_department_filter(user, db)
    if flt is not None:
        stmt = select(func.count()).select_from(Camera).where(flt).where(Camera.camera_id == camera_id)
        if not db.scalar(stmt):
            raise SentinelError("AUTH_FORBIDDEN", "Camera outside your department scope", 403)
    return cam


def query_cameras(
    db: Session,
    user,
    page: int,
    page_size: int,
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
):
    stmt = select(Camera).join(Department, Camera.department_id == Department.department_id)

    flt = user_department_filter(user, db)
    if flt is not None:
        stmt = stmt.where(flt)
    if department_id:
        stmt = stmt.where(Camera.department_id == department_id)
    if district:
        stmt = stmt.where(func.lower(Camera.district) == district.lower())
    if camera_type:
        stmt = stmt.where(Camera.camera_type == camera_type.upper())
    if status:
        stmt = stmt.where(Camera.status == status.upper())
    if connectivity:
        stmt = stmt.where(Camera.connectivity_status == connectivity.upper())
    if maintenance:
        stmt = stmt.where(Camera.maintenance_status == maintenance.upper())
    if storage:
        stmt = stmt.where(Camera.storage_type == storage.upper())
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Camera.name).like(like),
                func.lower(Camera.camera_code).like(like),
                func.lower(Camera.district).like(like),
                func.lower(func.coalesce(Camera.vendor, "")).like(like),
            )
        )
    if bbox:
        try:
            minx, miny, maxx, maxy = (float(v) for v in bbox.split(","))
        except ValueError:
            raise SentinelError("VALIDATION_ERROR", "bbox must be minLng,minLat,maxLng,maxLat", 400)
        stmt = stmt.where(
            Camera.longitude >= minx,
            Camera.longitude <= maxx,
            Camera.latitude >= miny,
            Camera.latitude <= maxy,
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    col_map = {
        "updated_at": Camera.updated_at,
        "created_at": Camera.created_at,
        "name": Camera.name,
        "camera_code": Camera.camera_code,
        "district": Camera.district,
    }
    desc = sort.startswith("-")
    col = col_map.get(sort.lstrip("-"), Camera.updated_at)
    stmt = stmt.order_by(col.desc() if desc else col.asc())

    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).scalars().all()
    return rows, int(total)


def to_dict(cam: Camera) -> dict:
    return {
        "camera_id": cam.camera_id,
        "camera_code": cam.camera_code,
        "name": cam.name,
        "department_id": cam.department_id,
        "site_id": cam.site_id,
        "camera_type": cam.camera_type,
        "ownership": cam.ownership,
        "public_facing": cam.public_facing,
        "vendor": cam.vendor,
        "model": cam.model,
        "ip_address": cam.ip_address,
        "latitude": cam.latitude,
        "longitude": cam.longitude,
        "district": cam.district,
        "taluka": cam.taluka,
        "address": cam.address,
        "connectivity_status": cam.connectivity_status,
        "last_seen_at": cam.last_seen_at.isoformat() if cam.last_seen_at else None,
        "storage_type": cam.storage_type,
        "retention_days": cam.retention_days,
        "install_date": cam.install_date.isoformat() if cam.install_date else None,
        "amc_vendor": cam.amc_vendor,
        "amc_end_date": cam.amc_end_date.isoformat() if cam.amc_end_date else None,
        "maintenance_status": cam.maintenance_status,
        "status": cam.status,
        "coverage_radius_m": cam.coverage_radius_m,
        "metadata": cam.metadata_json or {},
        "created_at": cam.created_at.isoformat() if cam.created_at else None,
        "updated_at": cam.updated_at.isoformat() if cam.updated_at else None,
    }
