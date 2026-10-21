"""Public promo-code validation.

Admin CRUD lives in routers/admin.py; checkout_multi (routers/orders.py)
reuses validate_promo() so validation rules live in exactly one place.
"""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/promos", tags=["promos"])

# validate_promo() reasons (also the contract for POST /api/promos/validate).
REASON_OK = "ok"
REASON_NOT_FOUND = "not found"
REASON_INACTIVE = "inactive"
REASON_EXPIRED = "expired"
REASON_USAGE_LIMIT = "usage limit reached"


def validate_promo(db: Session, raw_code: str | None) -> tuple[models.PromoCode | None, str]:
    """Validate a promo code. Returns (promo, reason).

    `reason` is one of "ok", "not found", "inactive", "expired",
    "usage limit reached". Never raises on bad input.
    """
    code = (raw_code or "").strip().upper()
    if not code:
        return None, REASON_NOT_FOUND
    promo = db.scalar(select(models.PromoCode).where(models.PromoCode.code == code))
    if promo is None:
        return None, REASON_NOT_FOUND
    if not promo.active:
        return None, REASON_INACTIVE
    exp = promo.expires_at
    if exp is not None:
        if exp.tzinfo is not None:
            exp = exp.astimezone(dt.timezone.utc).replace(tzinfo=None)
        if exp < dt.datetime.utcnow():
            return None, REASON_EXPIRED
    if promo.max_uses is not None and (promo.used_count or 0) >= promo.max_uses:
        return None, REASON_USAGE_LIMIT
    return promo, REASON_OK


@router.post("/validate", response_model=schemas.PromoValidateOut)
def validate_promo_endpoint(payload: schemas.PromoValidateIn, db: Session = Depends(get_db)):
    promo, reason = validate_promo(db, payload.code)
    return {
        "valid": promo is not None,
        "percent_off": promo.percent_off if promo is not None else 0,
        "reason": reason,
    }
