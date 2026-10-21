"""Loyalty points: settings, earn-on-completion, redeem refunds.

The LoyaltyLedger table is the append-only audit trail (reason:
earn | redeem | adjust); User.points_balance is the cached spendable
balance, always updated in the SAME transaction as the ledger write.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import models

# Seeded defaults for the Setting rows (see get_setting — lazy seeded).
DEFAULT_SETTINGS: dict[str, str] = {
    "points_per_dollar": "1",          # points earned per $1 of subtotal
    "points_per_dollar_redeem": "50",  # points needed for $1 off
}

EARN = "earn"
REDEEM = "redeem"
ADJUST = "adjust"


def get_setting(db: Session, key: str, default: int) -> int:
    """Read a numeric site setting, lazy-seeding the default row on first use.

    Returns `default` when the stored value is missing or not a positive int.
    The seeding write happens in the caller's transaction (flush only).
    """
    row = db.scalar(select(models.Setting).where(models.Setting.key == key))
    if row is None:
        seed = DEFAULT_SETTINGS.get(key, str(default))
        row = models.Setting(key=key, value=seed)
        db.add(row)
        db.flush()
    try:
        value = int(row.value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def set_setting(db: Session, key: str, value: int) -> None:
    """Upsert a numeric site setting (flush only; caller commits)."""
    row = db.scalar(select(models.Setting).where(models.Setting.key == key))
    if row is None:
        row = models.Setting(key=key, value=str(value))
        db.add(row)
    else:
        row.value = str(value)
    db.flush()


def reconcile_points_balances(db: Session) -> list[dict]:
    """Compare every user's cached points_balance against the sum of
    their LoyaltyLedger rows (DBA P1-2 safety net). The ledger is the
    source of truth; a mismatch means a lost update happened somewhere.
    Returns one dict per mismatched user (empty list = healthy)."""
    rows = db.execute(
        select(
            models.User.id,
            models.User.points_balance,
            func.coalesce(func.sum(models.LoyaltyLedger.delta), 0).label("ledger_sum"),
        )
        .outerjoin(models.LoyaltyLedger, models.LoyaltyLedger.user_id == models.User.id)
        .group_by(models.User.id)
    ).all()
    mismatches = []
    for user_id, balance, ledger_sum in rows:
        balance = balance or 0
        ledger_sum = int(ledger_sum)
        if balance != ledger_sum:
            mismatches.append({
                "user_id": user_id,
                "balance": balance,
                "ledger_sum": ledger_sum,
                "drift": balance - ledger_sum,
            })
    return mismatches


def award_completion_points(db: Session, order: models.Order) -> int:
    """Award loyalty points when an order transitions TO completed.

    floor(subtotal * points_per_dollar), guarded against double-award by an
    existing reason='earn' ledger row for the order. Guests earn nothing.
    Never raises: a loyalty failure must not break a status change.
    Returns the number of points awarded (0 when skipped).
    """
    try:
        if order.customer_id is None:
            return 0
        already = db.scalar(
            select(models.LoyaltyLedger.id).where(
                models.LoyaltyLedger.order_id == order.id,
                models.LoyaltyLedger.reason == EARN,
            )
        )
        if already is not None:
            return 0
        rate = get_setting(db, "points_per_dollar", 1)
        points = int(Decimal(order.subtotal or 0) * rate)  # floor
        if points <= 0:
            return 0
        user = db.get(models.User, order.customer_id)
        if user is None:
            return 0
        db.add(
            models.LoyaltyLedger(
                user_id=user.id,
                order_id=order.id,
                delta=points,
                reason=EARN,
                note=f"Order #{order.id} completed",
            )
        )
        # Atomic balance update (DBA P1-2): read-modify-write loses
        # concurrent updates (two completions both read 100, both add
        # 10, both write 110 — should be 120). The ledger row above is
        # the audit trail; this UPDATE keeps the cached balance in step.
        db.execute(
            update(models.User)
            .where(models.User.id == user.id)
            .values(points_balance=func.coalesce(models.User.points_balance, 0) + points)
        )
        db.expire(user, ["points_balance"])
        db.flush()
        return points
    except Exception as exc:  # noqa: BLE001 — points must never break the order flow
        print(f"[loyalty] earn failed: {exc}")
        return 0


def refund_redeemed_points(db: Session, order: models.Order) -> int:
    """Refund redeemed points when an order is cancelled BEFORE completion.

    Writes a reason='adjust' / note='cancel refund' ledger row and restores
    the balance. Skips when the order has no redeem rows, was already
    refunded, or already earned points (earn only fires on completed).
    Never raises. Returns the number of points refunded (0 when skipped).
    """
    try:
        if order.customer_id is None:
            return 0
        earned = db.scalar(
            select(models.LoyaltyLedger.id).where(
                models.LoyaltyLedger.order_id == order.id,
                models.LoyaltyLedger.reason == EARN,
            )
        )
        if earned is not None:
            return 0
        already_refunded = db.scalar(
            select(models.LoyaltyLedger.id).where(
                models.LoyaltyLedger.order_id == order.id,
                models.LoyaltyLedger.reason == ADJUST,
                models.LoyaltyLedger.note == "cancel refund",
            )
        )
        if already_refunded is not None:
            return 0
        redeemed = db.scalar(
            select(func.coalesce(func.sum(-models.LoyaltyLedger.delta), 0)).where(
                models.LoyaltyLedger.order_id == order.id,
                models.LoyaltyLedger.reason == REDEEM,
            )
        ) or 0
        if redeemed <= 0:
            return 0
        user = db.get(models.User, order.customer_id)
        if user is None:
            return 0
        db.add(
            models.LoyaltyLedger(
                user_id=user.id,
                order_id=order.id,
                delta=redeemed,
                reason=ADJUST,
                note="cancel refund",
            )
        )
        # Atomic balance update (DBA P1-2) — see award_completion_points.
        db.execute(
            update(models.User)
            .where(models.User.id == user.id)
            .values(points_balance=func.coalesce(models.User.points_balance, 0) + redeemed)
        )
        db.expire(user, ["points_balance"])
        db.flush()
        return redeemed
    except Exception as exc:  # noqa: BLE001 — refund must never break cancellation
        print(f"[loyalty] cancel refund failed: {exc}")
        return 0
