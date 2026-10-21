"""JWT auth: password hashing (bcrypt) + token issue/verify + role guards."""
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
from .database import get_db

log = logging.getLogger(__name__)

# Values that must NEVER be used to sign tokens. If SECRET_KEY is unset or
# matches one of these known placeholders, the app falls back to a random
# per-boot key (loudly logged) so a guessable key can never silently secure
# a deployment. Local dev keeps working; tokens just don't survive restarts.
# NOTE: with multiple uvicorn workers each worker gets its own random key —
# set a real SECRET_KEY env var for anything beyond single-process dev.
_KNOWN_BAD_KEYS = frozenset({
    "", "change-me-in-production", "changeme", "secret", "password",
    "test", "dev", "development", "placeholder",
})


def _resolve_secret_key() -> str:
    raw = (os.environ.get("SECRET_KEY") or "").strip()
    if raw and raw not in _KNOWN_BAD_KEYS:
        return raw
    key = secrets.token_urlsafe(48)
    log.warning(
        "NO USABLE SECRET_KEY CONFIGURED — using a random per-boot key. "
        "Set the SECRET_KEY env var to a strong random value for production "
        "(required for multi-worker setups and token persistence). "
        "Tokens issued now will stop working on restart."
    )
    return key


SECRET_KEY = _resolve_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # "iat" as a float timestamp (microsecond precision — python-jose would
    # truncate a datetime to whole seconds). Lets us invalidate tokens issued
    # before a password change with no granularity race.
    return jwt.encode(
        {"sub": subject, "iat": now.timestamp(), "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM,
    )


def create_download_token(subject: str) -> str:
    """v40 security fix (P1-1): short-lived, download-scoped token for the
    ?token= file-download endpoints. A leaked download URL must never grant
    full admin API access, so these tokens carry aud="download", live only
    60 seconds, and are rejected everywhere except the download endpoints."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(seconds=60)
    return jwt.encode(
        {"sub": subject, "iat": now.timestamp(), "exp": expire, "aud": "download"},
        SECRET_KEY, algorithm=ALGORITHM,
    )


def _token_predates_password_change(payload: dict, user: models.User) -> bool:
    """True if the token was issued before the user's last password change."""
    changed_at = user.password_changed_at
    if changed_at is None:
        return False
    iat = payload.get("iat")
    if iat is None:
        return True  # legacy token with no iat: treat as stale once a change happened
    try:
        issued_at = float(iat)
    except (TypeError, ValueError):
        return True
    changed_ts = changed_at.replace(tzinfo=timezone.utc).timestamp()
    # Full-precision comparison: the fresh token issued by change-password /
    # reset is created microseconds AFTER password_changed_at is set, so it
    # always validates; any token from before the change is dead.
    return issued_at < changed_ts


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", ""))
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if _token_predates_password_change(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired — please log in again",
        )
    if user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated by the admin",
        )
    return user


def get_optional_user(    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User | None:
    """Best-effort auth for public endpoints that personalize for the
    caller (e.g. dish lists hiding admin-moderated dishes from everyone
    except the owning vendor and the admin). Never raises: bad/missing
    tokens just mean 'anonymous'."""
    if creds is None:
        return None
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", ""))
    except (JWTError, ValueError):
        return None
    user = db.get(models.User, user_id)
    if user is None or user.is_active is False:
        return None
    if _token_predates_password_change(payload, user):
        return None
    return user


def require_vendor(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "vendor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vendor account required")
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin account required")
    return user


def require_staff(user: models.User = Depends(get_current_user)) -> models.User:
    """v40: staff role. Staff may handle support tickets/problems, view and
    change orders, and browse vendors/dishes — but NOT payouts, settings,
    users, analytics, or refunds (those stay require_admin)."""
    if user.role not in ("admin", "staff"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff account required")
    return user


def get_current_user_query_token(
    token: str | None = Query(default=None),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User:
    """v40: like get_current_user, but also accepts ?token=.

    File downloads (CSV exports, DB backup) are plain browser navigations
    that can't attach the Authorization header, so the frontend passes the
    JWT as ?token=. The header still takes precedence when present. All
    the same validation applies (expiry, password-change, deactivation).
    """
    raw = None
    from_query = False
    if creds is not None and creds.credentials:
        raw = creds.credentials
    elif token:
        raw = token
        from_query = True
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        # verify_aud off: python-jose rejects any token carrying an "aud"
        # claim when no audience is passed. We enforce aud="download" for
        # query tokens manually below; header session tokens carry no aud.
        payload = jwt.decode(raw, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_aud": False})
        user_id = int(payload.get("sub", ""))
    except (JWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if from_query and payload.get("aud") != "download":
        # SECURITY fix (v40 P1-1): session JWTs are rejected in URLs — URLs
        # land in access logs and browser history. Only short-lived scoped
        # download tokens (aud="download") may ride the query string.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Download token required — session tokens are not accepted in URLs",
        )
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if _token_predates_password_change(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired — please log in again",
        )
    if user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated by the admin",
        )
    return user


def require_admin_query_token(
    user: models.User = Depends(get_current_user_query_token),
) -> models.User:
    """v40: require_admin variant for ?token= download endpoints."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin account required")
    return user


def vendor_owned_by(vendor: models.Vendor, user: models.User) -> models.Vendor:
    if vendor.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your vendor")
    return vendor
