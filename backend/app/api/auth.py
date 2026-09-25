"""Authentication endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, get_current_user, get_user_permissions
from app.core.db import get_db
from app.core.errors import SentinelError, request_id_var
from app.core.security import create_access_token, verify_password
from app.models.user import Role, User, UserRole
from app.schemas.auth import LoginRequest
from app.services.audit import record

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_payload(user: User, db: Session) -> dict:
    perms = sorted(get_user_permissions(user, db))
    roles = db.execute(
        select(Role.name).join(UserRole, UserRole.role_name == Role.name).where(UserRole.user_id == user.user_id)
    ).scalars().all()
    return {
        "user_id": user.user_id,
        "name": user.name,
        "email": user.email,
        "status": user.status,
        "department_id": user.department_id,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "roles": roles,
        "permissions": perms,
        "requestId": None,
    }


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash) or user.status != "ACTIVE":
        if user:
            record(
                db, "LOGIN_FAILED", "user", user.user_id,
                actor_user_id=user.user_id, actor_label=user.email,
                ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
            )
            db.commit()
        raise SentinelError("AUTH_INVALID_CREDENTIALS", "Invalid email or password", 401)

    user.last_login_at = datetime.now(timezone.utc)
    record(
        db, "LOGIN_SUCCESS", "user", user.user_id,
        actor_user_id=user.user_id, actor_label=user.email,
        ip_address=client_ip(request), user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    token = create_access_token(user.user_id)
    return {
        "data": {"accessToken": token, "tokenType": "Bearer", "user": _user_payload(user, db)},
        "meta": {},
        "requestId": request_id_var.get(),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"data": _user_payload(user, db), "meta": {}, "requestId": request_id_var.get()}


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record(db, "LOGOUT", "user", user.user_id, actor_user_id=user.user_id, actor_label=user.email)
    db.commit()
    return {"data": {"ok": True}, "meta": {}, "requestId": request_id_var.get()}
