"""Expo push-token registration for the mobile app.

POST /api/push/register (auth): the app sends its ExpoPushToken after login
(and whenever it changes). Stored in the push_tokens table, keyed on the
token itself — a token moving between users (shared device, re-login) is
reassigned to the current caller.

DELETE /api/push/token (auth): remove the caller's token (logout hygiene).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db
from ..ratelimit import check_rate_limit

router = APIRouter(prefix="/api/push", tags=["push"])


class PushRegisterIn(BaseModel):
    expo_token: str
    platform: str | None = None  # ios | android

    @field_validator("expo_token")
    @classmethod
    def _token_shape(cls, v: str) -> str:
        v = (v or "").strip()
        # Real Expo tokens look like ExponentPushToken[xxxx…] or ExpoPushToken[xxxx…].
        if not v or len(v) > 255:
            raise ValueError("expo_token is required")
        if not (v.startswith("ExponentPushToken[") or v.startswith("ExpoPushToken[")):
            raise ValueError("not a valid Expo push token")
        return v

    @field_validator("platform")
    @classmethod
    def _platform_shape(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        return v if v in ("ios", "android") else None


@router.post("/register")
def register_push_token(
    payload: PushRegisterIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    check_rate_limit(request, "push_register", limit=30, window_seconds=3600)
    # Upsert keyed on the token itself: a device token is unique to the
    # device, so if it belonged to another user before, it moves over.
    row = (
        db.query(models.PushToken)
        .filter(models.PushToken.expo_token == payload.expo_token)
        .one_or_none()
    )
    if row is None:
        row = models.PushToken(
            user_id=user.id,
            expo_token=payload.expo_token,
            platform=payload.platform,
        )
        db.add(row)
    else:
        row.user_id = user.id
        row.platform = payload.platform
    db.commit()
    return {"ok": True}


class PushUnregisterIn(BaseModel):
    expo_token: str | None = None


@router.delete("/token")
def unregister_push_token(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
    payload: PushUnregisterIn | None = None,
):
    check_rate_limit(request, "push_unregister", limit=30, window_seconds=3600)
    q = db.query(models.PushToken).filter(models.PushToken.user_id == user.id)
    token = ((payload.expo_token if payload else None) or "").strip()
    if token:
        q = q.filter(models.PushToken.expo_token == token)
    q.delete(synchronize_session=False)
    db.commit()
    return {"ok": True}
