"""Meta/admin endpoints: departments, users, health."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import client_ip, get_current_user, get_user_permissions, require_perm
from app.core.errors import SentinelError, request_id_var
from app.core.security import hash_password
from app.models.department import Department
from app.models.user import Role, User, UserRole
from app.services import audit as audit_svc

router = APIRouter(tags=["meta"])


@router.get("/health/live")
def health_live():
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "up"}
    except Exception:
        raise SentinelError("DEPENDENCY_DOWN", "Database not reachable", 503)


@router.get("/departments")
def list_departments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(Department).where(Department.status == "ACTIVE").order_by(Department.name)).scalars().all()
    return {
        "data": [
            {"department_id": d.department_id, "name": d.name, "code": d.code, "status": d.status}
            for d in rows
        ],
        "meta": {},
        "requestId": request_id_var.get(),
    }


@router.post("/departments")
def create_department(
    body: dict,
    request: Request,
    user: User = Depends(require_perm("dept", "manage")),
    db: Session = Depends(get_db),
):
    name = str(body.get("name") or "").strip()
    code = str(body.get("code") or "").strip().upper()
    if not name or not code:
        raise SentinelError("VALIDATION_ERROR", "name and code are required", 422)
    if db.execute(select(Department).where(Department.code == code)).scalar_one_or_none():
        raise SentinelError("DEPARTMENT_CODE_EXISTS", "Department code already exists", 409)
    dept = Department(name=name, code=code, description=body.get("description"))
    db.add(dept)
    db.flush()
    audit_svc.record(
        db, "DEPARTMENT_CREATE", "department", dept.department_id,
        after_state={"name": name, "code": code},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return {"data": {"department_id": dept.department_id, "name": name, "code": code}, "meta": {}, "requestId": request_id_var.get()}


@router.get("/users")
def list_users(
    user: User = Depends(require_perm("user", "manage")),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(User).order_by(User.name)).scalars().all()
    role_rows = db.execute(select(UserRole.user_id, Role.name).join(Role, UserRole.role_name == Role.name)).all()
    roles_by_user: dict[str, list[str]] = {}
    for uid, rname in role_rows:
        roles_by_user.setdefault(uid, []).append(rname)
    return {
        "data": [
            {
                "user_id": u.user_id, "name": u.name, "email": u.email, "status": u.status,
                "department_id": u.department_id, "roles": roles_by_user.get(u.user_id, []),
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in rows
        ],
        "meta": {},
        "requestId": request_id_var.get(),
    }


@router.post("/users")
def create_user(
    body: dict,
    request: Request,
    user: User = Depends(require_perm("user", "manage")),
    db: Session = Depends(get_db),
):
    email = str(body.get("email") or "").strip().lower()
    name = str(body.get("name") or "").strip()
    password = str(body.get("password") or "")
    role_name = str(body.get("role") or "").strip().upper()
    department_id = body.get("department_id")

    if not email or not name or not password or not role_name:
        raise SentinelError("VALIDATION_ERROR", "name, email, password and role are required", 422)
    if len(password) < 8:
        raise SentinelError("VALIDATION_ERROR", "password must be at least 8 characters", 422)
    role = db.get(Role, role_name)
    if not role:
        raise SentinelError("ROLE_NOT_FOUND", f"Role '{role_name}' not found", 404)
    if role_name not in {"STATE_ADMIN", "AUDITOR"} and not department_id:
        raise SentinelError("VALIDATION_ERROR", f"department_id is required for role {role_name}", 422)
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise SentinelError("USER_EXISTS", "A user with this email already exists", 409)

    new_user = User(
        name=name, email=email, password_hash=hash_password(password),
        department_id=department_id, status="ACTIVE",
    )
    db.add(new_user)
    db.flush()
    db.add(UserRole(user_id=new_user.user_id, role_name=role_name, department_id=department_id))
    audit_svc.record(
        db, "USER_CREATE", "user", new_user.user_id,
        after_state={"email": email, "role": role_name, "department_id": department_id},
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return {
        "data": {"user_id": new_user.user_id, "name": name, "email": email, "role": role_name},
        "meta": {},
        "requestId": request_id_var.get(),
    }


@router.get("/roles")
def list_roles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Role).order_by(Role.name)).scalars().all()
    return {
        "data": [{"name": r.name, "description": r.description} for r in rows],
        "meta": {},
        "requestId": request_id_var.get(),
    }
