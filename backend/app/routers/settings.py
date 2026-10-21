"""Public site settings — auth-free.

The customer checkout preview needs the admin-set tax rate (set via
PUT /api/admin/settings) so the preview matches what the backend charges.
This endpoint exposes ONLY the two public-safe keys: tax_rate and
site_name. commission_percent and every other setting stay admin-only —
never add them here.
"""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Fallbacks when the Setting rows don't exist yet. Mirrors the defaults in
# routers/admin.py (_SETTING_DEFAULTS) for these two keys only.
_PUBLIC_DEFAULTS = {
    "tax_rate": "0.00",
    "site_name": "Egyptian Home Food Marketplace",
}


class PublicSettingsOut(BaseModel):
    tax_rate: float
    site_name: str


@router.get("/public", response_model=PublicSettingsOut)
def public_settings(db: Session = Depends(get_db)):
    """Auth-free public settings for the storefront preview.

    Returns the admin-set tax_rate (0.00 when unset or invalid) and the
    site_name. Nothing sensitive: commission_percent is deliberately
    excluded — it is stored for future use only and must never leak.
    """
    values: dict[str, str] = dict(_PUBLIC_DEFAULTS)
    for row in db.scalars(
        select(models.Setting).where(models.Setting.key.in_(list(_PUBLIC_DEFAULTS)))
    ):
        values[row.key] = row.value
    try:
        rate = Decimal(values["tax_rate"])
    except (InvalidOperation, ValueError):
        rate = Decimal("0.00")
    # NaN/Infinity parse fine but slip past every range comparison (both
    # are False for NaN) — and Pydantic rejects NaN floats with a 500.
    # is_finite() catches both. (Security P1-2.)
    if not rate.is_finite() or rate < 0 or rate > 1:
        rate = Decimal("0.00")
    return {"tax_rate": float(rate), "site_name": values["site_name"]}
