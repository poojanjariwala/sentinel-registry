import enum
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.department import uuid_pk


class CameraType(str, enum.Enum):
    FIXED = "FIXED"
    PTZ = "PTZ"
    DOME = "DOME"
    BULLET = "BULLET"
    ANPR = "ANPR"


class OwnershipType(str, enum.Enum):
    GOVERNMENT = "GOVERNMENT"
    PRIVATE = "PRIVATE"


class StorageType(str, enum.Enum):
    CLOUD = "CLOUD"
    LOCAL = "LOCAL"
    NVR = "NVR"
    NONE = "NONE"


class Camera(Base, TimestampMixin):
    __tablename__ = "cameras"
    __table_args__ = (
        Index("ix_cameras_department_status", "department_id", "status"),
        Index("ix_cameras_district_status", "district", "status"),
        Index("ix_cameras_camera_type", "camera_type"),
        Index("ix_cameras_maintenance", "maintenance_status"),
        Index("ix_cameras_location_gix", "location", postgresql_using="gist"),
    )

    camera_id: Mapped[str] = uuid_pk()
    camera_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.department_id"), nullable=False)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"))
    camera_type: Mapped[str] = mapped_column(String(50), default=CameraType.FIXED.value, nullable=False)
    ownership: Mapped[str] = mapped_column(String(30), default=OwnershipType.GOVERNMENT.value, nullable=False)
    public_facing: Mapped[bool] = mapped_column(default=False, nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    location = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    taluka: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    connectivity_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN", nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    storage_type: Mapped[str | None] = mapped_column(String(30))
    retention_days: Mapped[int | None] = mapped_column(Integer)
    install_date: Mapped[object | None] = mapped_column(Date)
    amc_vendor: Mapped[str | None] = mapped_column(String(150))
    amc_end_date: Mapped[object | None] = mapped_column(Date)
    maintenance_status: Mapped[str] = mapped_column(String(30), default="OK", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    coverage_radius_m: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB)

    department = relationship("Department")
    site = relationship("Site")
