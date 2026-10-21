"""Customer-facing loyalty endpoints.

/rates is PUBLIC (no auth) so the storefront can show "X points = $Y off"
without hardcoding the redeem rate. /balance and /ledger need a login.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, loyalty, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/loyalty", tags=["loyalty"])


@router.get("/rates", response_model=schemas.LoyaltyRatesOut)
def rates(db: Session = Depends(get_db)):
    """Public: the current earn/redeem rates (no auth needed)."""
    out = schemas.LoyaltyRatesOut(
        points_per_dollar=loyalty.get_setting(db, "points_per_dollar", 1),
        points_per_dollar_redeem=loyalty.get_setting(db, "points_per_dollar_redeem", 50),
    )
    db.commit()  # persist the lazy-seeded default rows, if any
    return out


@router.get("/balance", response_model=schemas.LoyaltyBalanceOut)
def balance(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    db.refresh(user)
    return schemas.LoyaltyBalanceOut(balance=user.points_balance or 0)


@router.get("/ledger", response_model=list[schemas.LoyaltyLedgerOut])
def ledger(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """The customer's points history, newest first (paginated, max 50/page)."""
    rows = db.scalars(
        select(models.LoyaltyLedger)
        .where(models.LoyaltyLedger.user_id == user.id)
        .order_by(models.LoyaltyLedger.created_at.desc(), models.LoyaltyLedger.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows)
