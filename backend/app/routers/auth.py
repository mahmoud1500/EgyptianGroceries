"""Auth routes: customer sign-up, login (customers + vendors), /me."""
import datetime as dt
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, emailer, models, schemas
from ..database import get_db
from ..ratelimit import check_rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=schemas.RegisterOut, status_code=201)
def register(
    payload: schemas.RegisterIn,
    request: Request,
    db: Session = Depends(get_db),
):
    check_rate_limit(request, "register", limit=20, window_seconds=3600)
    existing = db.scalar(select(models.User).where(models.User.email == payload.email.lower()))
    if existing:
        # Anti-enumeration: same shape as success, no login granted. Send the
        # existing account holder a sign-in nudge instead of leaking presence.
        token = secrets.token_urlsafe(32)
        db.add(
            models.PasswordResetToken(
                token=token,
                user_id=existing.id,
                expires_at=_utcnow() + dt.timedelta(hours=1),
            )
        )
        db.commit()
        try:
            emailer.send_password_reset(existing, token)
        except Exception:  # noqa: BLE001 — mail must never break the request
            pass
        return {"access_token": None, "token_type": "bearer", "registered": False}
    user = models.User(
        email=payload.email.lower(),
        hashed_password=auth.hash_password(payload.password),
        name=payload.name,
        role="customer",
        phone=payload.phone,
        address=payload.address,
        street_address=(payload.street_address or "").strip() or None,
        apt=(payload.apt or "").strip() or None,
        city=(payload.city or "").strip() or None,
        state=payload.state,  # already uppercased + validated by schema
        zipcode=payload.zipcode,
        # Email verification is OPTIONAL: login and checkout never block on it
        # (Resend may not be configured yet — the email just logs to console).
        verification_token=secrets.token_urlsafe(32),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    try:
        emailer.send_verification_email(user, user.verification_token)
    except Exception as exc:  # noqa: BLE001 — mail must never break signup
        print(f"[auth] verification email failed: {exc}")
    return {
        "access_token": auth.create_access_token(str(user.id)),
        "token_type": "bearer",
        "registered": True,
    }


@router.get("/verify-email")
def verify_email(
    token: str = Query(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    """Mark the account verified from the link in the signup email.

    Verifying is optional — unverified accounts can still log in and order.
    """
    user = db.scalar(
        select(models.User).where(models.User.verification_token == token)
    )
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    user.email_verified = True
    user.verification_token = None  # single use
    db.commit()
    return {"ok": True}


@router.post("/login", response_model=schemas.TokenOut)
def login(
    payload: schemas.LoginIn,
    request: Request,
    db: Session = Depends(get_db),
):
    check_rate_limit(request, "login", limit=10, window_seconds=600)
    user = db.scalar(select(models.User).where(models.User.email == payload.email.lower()))
    if user is None or not auth.verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    if user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated by the admin",
        )
    return {"access_token": auth.create_access_token(str(user.id))}


@router.get("/me", response_model=schemas.UserOut)
def me(user: models.User = Depends(auth.get_current_user)):
    return user


@router.patch("/me", response_model=schemas.UserOut)
def update_me(
    payload: schemas.ProfileUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    if payload.name is not None:
        user.name = payload.name.strip()
    if payload.phone is not None:
        user.phone = payload.phone.strip() or None
    if payload.address is not None:
        user.address = payload.address.strip() or None
    if payload.street_address is not None:
        user.street_address = payload.street_address.strip() or None
    if payload.apt is not None:
        user.apt = payload.apt.strip() or None
    if payload.city is not None:
        user.city = payload.city.strip() or None
    if payload.state is not None:
        user.state = payload.state  # already uppercased + validated by schema
    if payload.zipcode is not None:
        user.zipcode = payload.zipcode
    db.commit()
    db.refresh(user)
    return user


@router.post("/change-password")
def change_password(
    payload: schemas.PasswordChange,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    check_rate_limit(request, "change_password", limit=10, window_seconds=600)
    if not auth.verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.hashed_password = auth.hash_password(payload.new_password)
    # Invalidate all previously issued tokens (strict check in get_current_user).
    user.password_changed_at = _utcnow()
    db.commit()
    # Fresh token so the current session survives its own password change.
    return {"ok": True, "access_token": auth.create_access_token(str(user.id))}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


@router.post("/forgot")
def forgot_password(
    payload: schemas.ForgotIn,
    request: Request,
    db: Session = Depends(get_db),
):
    check_rate_limit(request, "forgot", limit=5, window_seconds=3600)
    # ALWAYS 200 — never reveal whether the email is registered.
    user = db.scalar(select(models.User).where(models.User.email == payload.email.lower()))
    if user is not None:
        token = secrets.token_urlsafe(32)
        db.add(
            models.PasswordResetToken(
                token=token,
                user_id=user.id,
                expires_at=_utcnow() + dt.timedelta(hours=1),
            )
        )
        db.commit()
        try:
            emailer.send_password_reset(user, token)
        except Exception as exc:  # noqa: BLE001 — mail must never break the request
            print(f"[auth] password-reset email failed: {exc}")
    return {"ok": True}


@router.post("/reset")
def reset_password(
    payload: schemas.ResetIn,
    request: Request,
    db: Session = Depends(get_db),
):
    check_rate_limit(request, "reset", limit=10, window_seconds=3600)
    rec = db.scalar(select(models.PasswordResetToken).where(models.PasswordResetToken.token == payload.token))
    if rec is None or rec.used or rec.expires_at < _utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user = db.get(models.User, rec.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    user.hashed_password = auth.hash_password(payload.new_password)
    # Invalidate all previously issued tokens.
    user.password_changed_at = _utcnow()
    rec.used = True
    db.commit()
    return {"ok": True}
