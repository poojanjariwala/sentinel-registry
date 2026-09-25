from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.errors import SentinelError

settings = get_settings()


def hash_password(password: str) -> str:
    # bcrypt hashes at most 72 bytes; pre-hash long secrets deterministically.
    if len(password.encode("utf-8")) > 72:
        import hashlib

        password = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if len(password.encode("utf-8")) > 72:
        import hashlib

        password = hashlib.sha256(password.encode("utf-8")).hexdigest()
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise SentinelError("AUTH_INVALID_TOKEN", "Invalid or expired session token", 401)
    sub = payload.get("sub")
    if not sub:
        raise SentinelError("AUTH_INVALID_TOKEN", "Invalid or expired session token", 401)
    return sub
