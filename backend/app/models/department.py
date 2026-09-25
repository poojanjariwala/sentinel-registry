from datetime import datetime
from uuid import uuid4

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Double, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


def uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    department_id: Mapped[str] = uuid_pk()
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)

    sites: Mapped[list["Site"]] = relationship(back_populates="department")


class Site(Base, TimestampMixin):
    __tablename__ = "sites"

    site_id: Mapped[str] = uuid_pk()
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.department_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    taluka: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    location = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)

    department: Mapped[Department] = relationship(back_populates="sites")
