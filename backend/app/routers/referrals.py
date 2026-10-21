"""F2: vendor share links + referral earnings (Oct 2026).

- GET /v/<code> — short public share link. Redirects to the vendor's
  storefront with ?ref=<code> set (404 on unknown codes).
- GET /api/vendors/{vendor_id}/referrals — the vendor's OWN attributed
  orders + computed rebate earned (display only, no money moves in v1).
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, models, referrals, schemas
from ..database import get_db

router = APIRouter(tags=["referrals"])


@router.get("/v/{code}")
def vendor_share_redirect(code: str, db: Session = Depends(get_db)):
    """Short share link: /v/AB12CD34 -> the vendor's storefront with ?ref= set.

    404 on unknown codes so a typo'd link says so instead of landing
    somewhere meaningless. The customer site reads ?ref= from the hash
    and sends referral_code at checkout — the server re-validates it.
    """
    vendor = referrals.resolve_referral(db, code)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Unknown share code")
    return RedirectResponse(
        url=f"/#/vendor/{vendor.id}?ref={vendor.referral_code}", status_code=302
    )


@router.get(
    "/api/vendors/{vendor_id}/referrals",
    response_model=schemas.ReferralEarningsOut,
)
def referral_earnings(
    vendor_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Attributed orders + computed rebate for the vendor's OWN shop.

    Rebate = subtotal * referral_rebate_percent / 100 per attributed
    (non-cancelled) order. Display only — no money moves in v1.
    """
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    auth.vendor_owned_by(vendor, user)
    pct = referrals.get_rebate_percent(db)
    rows = list(
        db.scalars(
            select(models.Order)
            .where(
                models.Order.attributed_vendor_id == vendor_id,
                models.Order.status != "cancelled",
            )
            .order_by(models.Order.created_at.desc())
        ).all()
    )
    orders_out: list[schemas.AttributedOrderOut] = []
    total = Decimal("0")
    for o in rows:
        rebate = (Decimal(o.subtotal or 0) * pct / Decimal(100)).quantize(
            Decimal("0.01")
        )
        total += rebate
        orders_out.append(
            schemas.AttributedOrderOut(
                id=o.id,
                created_at=o.created_at,
                subtotal=Decimal(o.subtotal or 0),
                total=Decimal(o.total or 0),
                status=o.status,
                rebate=rebate,
            )
        )
    return schemas.ReferralEarningsOut(
        vendor_id=vendor_id,
        referral_code=vendor.referral_code,
        rebate_percent=pct,
        attributed_orders=orders_out,
        total_rebate=total,
    )
