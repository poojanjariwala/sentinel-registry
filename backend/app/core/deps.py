"""FastAPI dependencies for authentication and permission checks."""

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import SentinelError
from app.core.security import decode_access_token
from app.models.user import Permission, Role, User, UserRole

# Role -> permission names granted by default.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "STATE_ADMIN": [p for p in (
        "camera.read", "camera.write", "camera.delete", "camera.import", "camera.export",
        "coverage.run", "audit.read", "user.manage", "dept.manage",
    )],
    "DEPARTMENT_ADMIN": ["camera.read", "camera.write", "camera.delete", "camera.import", "camera.export", "coverage.run", "dept.manage"],
    "OPERATOR": ["camera.read", "camera.write", "camera.import", "camera.export", "coverage.run", "stream.watch", "analytics.tag", "alert.manage"],
    "AUDITOR": ["audit.read"],
    "VIEWER": ["camera.read", "coverage.run", "stream.watch"],
}


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise SentinelError("AUTH_UNAUTHENTICATED", "Authentication required", 401)
    user_id = decode_access_token(auth.removeprefix("Bearer ").strip())
    user = db.get(User, user_id)
    if not user or user.status != "ACTIVE":
        raise SentinelError("AUTH_INVALID_TOKEN", "User account is not active", 401)
    request.state.user = user
    return user


def get_user_permissions(user: User, db: Session) -> set[str]:
    """Effective permissions = role defaults + explicit DB grants/denials."""
    roles = db.execute(
        select(Role.name).join(UserRole, UserRole.role_name == Role.name).where(UserRole.user_id == user.user_id)
    ).scalars().all()
    perms: set[str] = set()
    for r in roles:
        perms.update(ROLE_PERMISSIONS.get(r, []))
    extra = db.execute(select(Permission).where(Permission.user_id == user.user_id)).scalars().all()
    for p in extra:
        if p.granted:
            perms.add(f"{p.resource}.{p.action}")
        else:
            perms.discard(f"{p.resource}.{p.action}")
    return perms


def require_perm(resource: str, action: str):
    """Dependency factory enforcing a named permission."""

    def checker(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        perms = get_user_permissions(user, db)
        if f"{resource}.{action}" not in perms:
            raise SentinelError("AUTH_FORBIDDEN", "You do not have permission to perform this action", 403)
        request.state.user = user
        return user

    return checker


def get_user_department_ids(user: User, db: Session) -> list[str] | None:
    """Department ids in the user's scope.

    Returns None when unrestricted (state-wide roles: STATE_ADMIN, AUDITOR),
    otherwise the list of department ids granted via user_roles.
    """
    unrestricted_roles = {"STATE_ADMIN", "AUDITOR"}
    rows = db.execute(
        select(Role.name, UserRole.department_id)
        .join(UserRole, UserRole.role_name == Role.name)
        .where(UserRole.user_id == user.user_id)
    ).all()
    if any(r in unrestricted_roles for (r, _) in rows):
        return None
    return [dept_id for (_, dept_id) in rows if dept_id]


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None
