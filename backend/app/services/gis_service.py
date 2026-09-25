"""GIS service - GeoJSON FeatureCollection output for map layers."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import SentinelError
from app.models.camera import Camera
from app.models.department import Department
from app.services.camera_service import user_department_filter


def _feature(cam: Camera, department_name: str | None) -> dict:
    props = {
        "camera_id": cam.camera_id,
        "camera_code": cam.camera_code,
        "name": cam.name,
        "department_id": cam.department_id,
        "department_name": department_name,
        "camera_type": cam.camera_type,
        "ownership": cam.ownership,
        "public_facing": cam.public_facing,
        "status": cam.status,
        "connectivity_status": cam.connectivity_status,
        "maintenance_status": cam.maintenance_status,
        "district": cam.district,
        "vendor": cam.vendor,
    }
    return {
        "type": "Feature",
        "id": cam.camera_id,
        "geometry": {"type": "Point", "coordinates": [cam.longitude, cam.latitude]},
        "properties": props,
    }


def cameras_geojson(
    db: Session,
    user,
    department_id: str | None = None,
    district: str | None = None,
    camera_type: str | None = None,
    status: str | None = None,
    connectivity: str | None = None,
    bbox: str | None = None,
) -> dict:
    stmt = (
        select(Camera, Department.name)
        .join(Department, Camera.department_id == Department.department_id)
        .where(Camera.latitude.is_not(None), Camera.longitude.is_not(None))
    )
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
    if bbox:
        try:
            minx, miny, maxx, maxy = (float(v) for v in bbox.split(","))
        except ValueError:
            raise SentinelError("VALIDATION_ERROR", "bbox must be minLng,minLat,maxLng,maxLat", 400)
        stmt = stmt.where(
            Camera.longitude >= minx, Camera.longitude <= maxx,
            Camera.latitude >= miny, Camera.latitude <= maxy,
        )

    features = [_feature(cam, dname) for cam, dname in db.execute(stmt.limit(10000)).all()]
    return {"type": "FeatureCollection", "features": features}
