from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.department import uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    user_id: Mapped[str] = uuid_pk()
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.department_id"))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    permissions_json: Mapped[dict | None] = mapped_column("permissions", JSONB)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)


class UserRole(Base, TimestampMixin):
    __tablename__ = "user_roles"

    user_role_id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    role_name: Mapped[str] = mapped_column(ForeignKey("roles.name"), nullable=False)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.department_id"))


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    permission_id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), nullable=False)
    resource: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_type: Mapped[str | None] = mapped_column(String(50))
    granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
