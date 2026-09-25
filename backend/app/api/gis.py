"""GIS endpoints: GeoJSON camera layer."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_perm
from app.core.errors import request_id_var
from app.services.gis_service import cameras_geojson

router = APIRouter(prefix="/gis", tags=["gis"])


@router.get("/cameras")
def gis_cameras(
    department_id: str | None = None,
    district: str | None = None,
    camera_type: str | None = None,
    status: str | None = None,
    connectivity: str | None = None,
    bbox: str | None = None,
    user=Depends(require_perm("camera", "read")),
    db: Session = Depends(get_db),
):
    fc = cameras_geojson(db, user, department_id, district, camera_type, status, connectivity, bbox)
    return {"data": fc, "meta": {"count": len(fc["features"])}, "requestId": request_id_var.get()}
