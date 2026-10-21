"""Admin back-office: the site owner sees everything and can fix orders.

All routes require the admin role. Powers the Admin section of the
vendor portal (visible only when logged in as admin)."""
import datetime as dt
import json
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case as sa_case
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from .. import auth, emailer, loyalty, models, notifier, schemas
from ..database import engine, get_db
from .dishes import (
    _attach_ingredient_options,
    _attach_options,
    _attach_ratings,
    sweep_orphan_uploads,
)
from .orders import (
    _ORDER_FLOW,
    _log_event,
    _restore_stock_on_cancel,
    _serialize,
    _stripe_payment_intent_id,
    _stripe_refund_on_cancel,
)
from .stripe import _stripe_client

router = APIRouter(prefix="/api/admin", tags=["admin"])


def log_admin_action(
    db: Session,
    admin: models.User,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict | None = None,
) -> None:
    """Append one AdminAuditLog row. Callers flush/commit; this only adds.
    details must be JSON-serializable (stored as a JSON string)."""
    db.add(
        models.AdminAuditLog(
            admin_user_id=admin.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=json.dumps(details or {}),
        )
    )


def _audit_row(log: models.AdminAuditLog, admin_name: str | None) -> dict:
    try:
        details = json.loads(log.details) if log.details else {}
    except (ValueError, TypeError):
        details = {}
    return {
        "id": log.id,
        "admin_user_id": log.admin_user_id,
        "admin_name": admin_name,
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "details": details,
        "created_at": log.created_at,
    }


# Site-settings keys stored in the Setting key-value table.
_SETTING_DEFAULTS = {
    "tax_rate": "0.00",
    "commission_percent": "0",
    "site_name": "Egyptian Home Food Marketplace",
    # F2: referral rebate percent (display-only in v1 — no money moves).
    "referral_rebate_percent": "2",
    # v40: admin alert toggles (1 = on) + SMS destination + last backup time.
    "alert_orders": "1",
    "alert_applications": "1",
    "alert_tickets": "1",
    "alert_phone": "",
    "last_backup_at": "",
}


def _admin(user: models.User = Depends(auth.require_admin)) -> models.User:
    return user


def _staff(user: models.User = Depends(auth.require_staff)) -> models.User:
    """v40: admin OR staff. Staff may handle support tickets/problems, view
    and change orders, and browse vendors/dishes. Payouts, settings, users,
    analytics, refunds, and moderation stay admin-only (_admin)."""
    return user


def _admin_dl(
    user: models.User = Depends(auth.require_admin_query_token),
) -> models.User:
    """v40: admin guard for ?token= file downloads (CSV exports, backup) —
    plain navigations can't carry the Authorization header. Only short-lived
    scoped download tokens (aud="download", 60s) are accepted in URLs."""
    return user


@router.post("/download-token")
def mint_download_token(admin: models.User = Depends(_admin)):
    """Mint a 60-second download-scoped token for the CSV/backup buttons.
    Authenticated via the normal session header; the returned token is the
    only thing allowed to ride the ?token= query string."""
    return {"token": auth.create_download_token(str(admin.id))}


# === v40: money controls — commission + per-vendor money summary ===
def _commission_default(db: Session) -> Decimal:
    """Global commission percent from the Setting table (falls back to the
    code default when missing/corrupt)."""
    row = db.scalar(
        select(models.Setting).where(models.Setting.key == "commission_percent")
    )
    if row is not None:
        try:
            return Decimal(str(row.value))
        except (InvalidOperation, ValueError, TypeError):
            pass
    return Decimal(_SETTING_DEFAULTS["commission_percent"])


def _vendor_money(
    db: Session,
    vendor: models.Vendor,
    gross: Decimal,
    paid: Decimal,
    default_rate: Decimal,
) -> dict:
    """Per-vendor money summary for COMPLETED orders only.

    gross = sum(order.total); commission = gross * rate/100 where rate is
    the vendor's own commission_rate or the global default; paid = sum of
    recorded payouts; owed = gross − commission − paid.
    """
    rate = (
        Decimal(str(vendor.commission_rate))
        if vendor.commission_rate is not None
        else default_rate
    )
    commission = (gross * rate / Decimal(100)).quantize(Decimal("0.01"))
    owed = gross - commission - paid
    return {
        "commission_rate": float(rate),
        "gross": float(gross),
        "commission": float(commission),
        "paid": float(paid),
        "owed": float(owed),
    }
# === END v40 ===


@router.get("/stats")
def stats(db: Session = Depends(get_db), admin: models.User = Depends(_staff)):
    revenue = db.scalar(
        select(func.coalesce(func.sum(models.Order.total), 0)).where(
            models.Order.status != "cancelled"
        )
    )
    return {
        "revenue": float(revenue or 0),
        "orders": db.scalar(select(func.count()).select_from(models.Order)) or 0,
        "customers": db.scalar(
            select(func.count()).select_from(models.User).where(models.User.role == "customer")
        )
        or 0,
        "vendors": db.scalar(select(func.count()).select_from(models.Vendor)) or 0,
        "dishes": db.scalar(select(func.count()).select_from(models.Dish)) or 0,
        "open_complaints": db.scalar(
            select(func.count())
            .select_from(models.Complaint)
            .where(models.Complaint.status == "open")
        )
        or 0,
        "new_orders": db.scalar(
            select(func.count())
            .select_from(models.Order)
            .where(models.Order.status == "new")
        )
        or 0,
    }


@router.get("/orders", response_model=list[schemas.OrderOut])
def all_orders(
    status: str | None = Query(default=None, max_length=20),
    vendor_id: int | None = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_staff),
):
    stmt = (
        select(models.Order)
        .options(
            joinedload(models.Order.items),
            joinedload(models.Order.customer),
            joinedload(models.Order.vendor),
        )
        .order_by(models.Order.created_at.desc())
    )
    if status:
        stmt = stmt.where(models.Order.status == status.strip().lower())
    if vendor_id:
        stmt = stmt.where(models.Order.vendor_id == vendor_id)
    return [_serialize(o) for o in db.scalars(stmt).unique().all()]


@router.get("/customers")
def all_customers(db: Session = Depends(get_db), admin: models.User = Depends(_admin)):
    users = list(
        db.scalars(
            select(models.User)
            .where(models.User.role == "customer")
            .order_by(models.User.created_at.desc())
        )
    )
    out = []
    for u in users:
        agg = db.execute(
            select(
                func.count(models.Order.id),
                func.coalesce(func.sum(models.Order.total), 0),
                func.min(models.Order.created_at),
                func.max(models.Order.created_at),
            ).where(models.Order.customer_id == u.id, models.Order.status != "cancelled")
        ).one()
        out.append(
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "phone": u.phone,
                "city": u.city,
                "state": u.state,
                "orders": int(agg[0] or 0),
                "total_spent": float(agg[1] or 0),
                "first_order": agg[2].isoformat() if agg[2] else None,
                "last_order": agg[3].isoformat() if agg[3] else None,
            }
        )
    return out


@router.get("/vendors")
def all_vendors(db: Session = Depends(get_db), admin: models.User = Depends(_staff)):
    vendors = list(db.scalars(select(models.Vendor).order_by(models.Vendor.name)))
    # === v40: money summary inputs, aggregated once for all vendors. ===
    default_rate = _commission_default(db)
    gross_by_vendor = dict(
        db.execute(
            select(
                models.Order.vendor_id,
                func.coalesce(func.sum(models.Order.total), 0),
            )
            .where(models.Order.status == "completed")
            .group_by(models.Order.vendor_id)
        ).all()
    )
    paid_by_vendor = dict(
        db.execute(
            select(
                models.VendorPayout.vendor_id,
                func.coalesce(func.sum(models.VendorPayout.amount), 0),
            ).group_by(models.VendorPayout.vendor_id)
        ).all()
    )
    # === END v40 ===
    out = []
    for v in vendors:
        owner = db.get(models.User, v.owner_id) if v.owner_id else None
        dishes = (
            db.scalar(select(func.count()).select_from(models.Dish).where(models.Dish.vendor_id == v.id))
            or 0
        )
        agg = db.execute(
            select(
                func.count(models.Order.id),
                func.coalesce(func.sum(models.Order.total), 0),
                func.max(models.Order.created_at),
            ).where(models.Order.vendor_id == v.id, models.Order.status != "cancelled")
        ).one()
        addr = ", ".join(
            p for p in [v.street_address, v.city, v.state, v.zipcode] if p
        )
        # === v40: per-vendor money summary (completed orders only). ===
        money = _vendor_money(
            db,
            v,
            Decimal(str(gross_by_vendor.get(v.id, 0) or 0)),
            Decimal(str(paid_by_vendor.get(v.id, 0) or 0)),
            default_rate,
        )
        # === END v40 ===
        out.append(
            {
                "id": v.id,
                "name": v.name,
                "tagline": v.tagline,
                "area": v.area,
                "address": addr or None,
                "phone": v.phone or (owner.phone if owner else None),
                "owner_name": owner.name if owner else None,
                "owner_email": owner.email if owner else None,
                "fulfillment": v.fulfillment,
                "delivery_fee": float(v.delivery_fee or 0),
                "dishes": int(dishes),
                "orders": int(agg[0] or 0),
                "revenue": float(agg[1] or 0),
                "last_order": agg[2].isoformat() if agg[2] else None,
                # === v40 ===
                "commission_rate": money["commission_rate"],
                "gross": money["gross"],
                "commission": money["commission"],
                "paid": money["paid"],
                "owed": money["owed"],
                "is_paused": v.is_paused,
                # === END v40 ===
            }
        )
    return out


@router.get("/retention")
def retention(db: Session = Depends(get_db), admin: models.User = Depends(_admin)):
    now = dt.datetime.utcnow()
    d30 = now - dt.timedelta(days=30)
    # Per-customer order counts + first/last order dates (non-cancelled orders).
    rows = list(
        db.execute(
            select(
                models.Order.customer_id,
                func.count(models.Order.id),
                func.min(models.Order.created_at),
                func.max(models.Order.created_at),
            )
            .where(models.Order.status != "cancelled")
            .group_by(models.Order.customer_id)
        ).all()
    )
    total_c = len(rows)
    repeat_c = sum(1 for r in rows if (r[1] or 0) >= 2)
    new_30 = sum(1 for r in rows if r[2] and r[2] >= d30)
    returning_30 = sum(1 for r in rows if r[3] and r[3] >= d30 and r[2] and r[2] < d30)
    avg_orders = round(sum(r[1] or 0 for r in rows) / total_c, 2) if total_c else 0
    # Per-vendor activity.
    vrows = list(
        db.execute(
            select(
                models.Order.vendor_id,
                func.count(models.Order.id),
                func.max(models.Order.created_at),
            )
            .where(models.Order.status != "cancelled")
            .group_by(models.Order.vendor_id)
        ).all()
    )
    total_v = db.scalar(select(func.count()).select_from(models.Vendor)) or 0
    active_v = sum(1 for r in vrows if r[2] and r[2] >= d30)
    with_orders = len(vrows)
    idle_vendors = []
    if total_v:
        active_ids = {r[0] for r in vrows if r[2] and r[2] >= d30}
        for v in db.scalars(select(models.Vendor)):
            if v.id not in active_ids:
                idle_vendors.append({"id": v.id, "name": v.name})
    return {
        "customers": {
            "total": total_c,
            "repeat": repeat_c,
            "repeat_rate": round(repeat_c / total_c * 100, 1) if total_c else 0,
            "one_time": total_c - repeat_c,
            "new_30d": new_30,
            "returning_30d": returning_30,
            "avg_orders": avg_orders,
        },
        "vendors": {
            "total": total_v,
            "active_30d": active_v,
            "active_rate": round(active_v / total_v * 100, 1) if total_v else 0,
            "with_orders": with_orders,
            "idle": idle_vendors,
        },
    }


# === v40: admin analytics ===
@router.get("/analytics")
def analytics(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin analytics: revenue over time, revenue by vendor, top dishes,
    peak order hours/days, repeat-customer rate, new vs returning.

    All metrics from COMPLETED orders in the last `days` days. Day/hour
    buckets use America/Los_Angeles (the marketplace timezone).
    Read-only; admin-only.
    """
    from zoneinfo import ZoneInfo

    LA = ZoneInfo("America/Los_Angeles")
    start_utc = dt.datetime.utcnow() - dt.timedelta(days=days)

    orders = list(
        db.scalars(
            select(models.Order).where(
                models.Order.status == "completed",
                models.Order.created_at >= start_utc,
            )
        ).all()
    )

    def _la(o: models.Order) -> dt.datetime:
        created = o.created_at or dt.datetime.utcnow()
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        return created.astimezone(LA)

    # --- revenue over time (per LA day, zero-filled) ---
    day_map: dict[str, dict] = {}
    for i in range(days):
        d = (dt.datetime.now(LA) - dt.timedelta(days=days - 1 - i)).date().isoformat()
        day_map[d] = {"date": d, "gross": 0.0, "orders": 0}
    for o in orders:
        key = _la(o).date().isoformat()
        bucket = day_map.get(key)
        if bucket is not None:
            bucket["gross"] = round(bucket["gross"] + float(o.total or 0), 2)
            bucket["orders"] += 1

    # --- revenue by vendor (SQL) ---
    vendor_rows = db.execute(
        select(
            models.Order.vendor_id,
            models.Vendor.name,
            func.count(models.Order.id),
            func.coalesce(func.sum(models.Order.total), 0),
        )
        .join(models.Vendor, models.Vendor.id == models.Order.vendor_id)
        .where(
            models.Order.status == "completed",
            models.Order.created_at >= start_utc,
        )
        .group_by(models.Order.vendor_id, models.Vendor.name)
        .order_by(func.coalesce(func.sum(models.Order.total), 0).desc())
    ).all()

    # --- top dishes by revenue (SQL, snapshot prices survive later edits) ---
    dish_rows = db.execute(
        select(
            models.OrderItem.dish_id,
            models.OrderItem.dish_name,
            models.Vendor.name,
            func.coalesce(func.sum(models.OrderItem.quantity), 0),
            func.coalesce(
                func.sum(models.OrderItem.quantity * models.OrderItem.unit_price), 0
            ),
        )
        .join(models.Order, models.Order.id == models.OrderItem.order_id)
        .join(models.Dish, models.Dish.id == models.OrderItem.dish_id)
        .join(models.Vendor, models.Vendor.id == models.Dish.vendor_id)
        .where(
            models.Order.status == "completed",
            models.Order.created_at >= start_utc,
            models.OrderItem.dish_id.isnot(None),
        )
        .group_by(models.OrderItem.dish_id, models.OrderItem.dish_name, models.Vendor.name)
        .order_by(
            func.coalesce(
                func.sum(models.OrderItem.quantity * models.OrderItem.unit_price), 0
            ).desc()
        )
        .limit(10)
    ).all()

    # --- peak hours / days (Python bucketing in LA) ---
    peak_hours = [{"hour": h, "orders": 0} for h in range(24)]
    peak_days = [{"weekday": w, "orders": 0} for w in range(7)]  # 0=Monday
    for o in orders:
        local = _la(o)
        peak_hours[local.hour]["orders"] += 1
        peak_days[local.weekday()]["orders"] += 1

    # --- repeat rate + new vs returning (account customers only) ---
    per_customer: dict[int, int] = {}
    for o in orders:
        if o.customer_id is not None:
            per_customer[o.customer_id] = per_customer.get(o.customer_id, 0) + 1
    total_c = len(per_customer)
    repeat_c = sum(1 for n in per_customer.values() if n >= 2)
    first_ever = dict(
        db.execute(
            select(
                models.Order.customer_id,
                func.min(models.Order.created_at),
            )
            .where(
                models.Order.status == "completed",
                models.Order.customer_id.isnot(None),
            )
            .group_by(models.Order.customer_id)
        ).all()
    )
    new_c = sum(
        1 for cid in per_customer
        if first_ever.get(cid) is not None and first_ever[cid].replace(tzinfo=None) >= start_utc
    )

    gross = round(sum(float(o.total or 0) for o in orders), 2)
    return {
        "days": days,
        "totals": {
            "gross": gross,
            "orders": len(orders),
            "avg_order": round(gross / len(orders), 2) if orders else 0,
            "customers": total_c,
        },
        "revenue_over_time": list(day_map.values()),
        "revenue_by_vendor": [
            {
                "vendor_id": r[0],
                "vendor_name": r[1],
                "orders": int(r[2] or 0),
                "gross": round(float(r[3] or 0), 2),
            }
            for r in vendor_rows
        ],
        "top_dishes": [
            {
                "dish_id": r[0],
                "dish_name": r[1],
                "vendor_name": r[2],
                "units": int(r[3] or 0),
                "revenue": round(float(r[4] or 0), 2),
            }
            for r in dish_rows
        ],
        "peak_hours": peak_hours,
        "peak_days": peak_days,
        "repeat_rate": round(repeat_c / total_c * 100, 1) if total_c else 0,
        "new_customers": new_c,
        "returning_customers": total_c - new_c,
    }
# === END v40 ===
@router.patch("/orders/{order_id}/status", response_model=schemas.OrderOut)
def admin_set_status(
    order_id: int,
    payload: schemas.OrderStatusUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_staff),
):
    """Admin can move any order to any valid status (to fix mistakes)."""
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    target = payload.status
    if target not in _ORDER_FLOW and target != "cancelled":
        raise HTTPException(status_code=400, detail="Invalid status")
    if target == "on_the_way" and order.fulfillment != "delivery":
        raise HTTPException(
            status_code=400,
            detail="The 'on the way' status is only for delivery orders",
        )
    previous = order.status
    if previous == "cancelled" and target != "cancelled":
        raise HTTPException(status_code=400, detail="Cancelled orders cannot be reopened")
    if target == previous:
        return _serialize(order)
    order.status = target
    db.flush()
    _log_event(
        db,
        order,
        "status",
        f"Status changed by admin ({admin.name})",
        {"from": previous, "to": target, "by": admin.name, "by_role": "admin"},
    )
    if target == "cancelled":
        _stripe_refund_on_cancel(db, order)  # refunds only paid card orders; never breaks cancel
        # Loyalty: refund redeemed points — but never when points were already
        # earned (earn only fires on completed; the helper guards anyway).
        refunded = loyalty.refund_redeemed_points(db, order)
        if refunded:
            _log_event(
                db, order, "points",
                f"Refunded {refunded} redeemed loyalty points (order cancelled)",
                {"points": refunded},
            )
        # Stock: restore ordered quantities (cancel_restore). Runs once —
        # cancelling an already-cancelled order is rejected above.
        _restore_stock_on_cancel(db, order)
    log_admin_action(
        db, admin, "order_status", "order", order.id,
        {"from": previous, "to": target},
    )
    if target == "completed":
        # Loyalty: award points on the transition TO completed (double-award
        # guarded by the helper; cancelled orders can't reach here).
        earned = loyalty.award_completion_points(db, order)
        if earned:
            _log_event(
                db, order, "points",
                f"Awarded {earned} loyalty points",
                {"points": earned},
            )
    db.commit()
    db.refresh(order)
    try:
        emailer.send_order_status_update(order, previous, target)
    except Exception as exc:  # noqa: BLE001
        print(f"[admin] status email failed: {exc}")
    # SMS the customer about the status change — best effort, never breaks it.
    try:
        notifier.send_order_status_sms(db, order, target)
    except Exception as exc:  # noqa: BLE001
        print(f"[admin] status SMS failed: {exc}")
    return _serialize(order)


@router.get("/payouts")
def list_payouts(db: Session = Depends(get_db), admin: models.User = Depends(_admin)):
    """Ledger of every off-system settlement with vendors (see VendorPayout)."""
    rows = list(
        db.execute(
            select(models.VendorPayout, models.Vendor.name)
            .join(models.Vendor, models.Vendor.id == models.VendorPayout.vendor_id)
            .order_by(models.VendorPayout.created_at.desc())
        ).all()
    )
    return [
        {
            "id": p.id,
            "vendor_id": p.vendor_id,
            "vendor_name": name,
            "amount": float(p.amount),
            "note": p.note,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p, name in rows
    ]


@router.post("/payouts", response_model=schemas.PayoutOut, status_code=201)
def create_payout(
    payload: schemas.PayoutCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Record an off-system payment to a vendor (owner pays outside the app,
    then logs it here)."""
    vendor = db.get(models.Vendor, payload.vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    payout = models.VendorPayout(
        vendor_id=vendor.id,
        amount=payload.amount,
        note=(payload.note or "").strip() or None,
    )
    db.add(payout)
    db.commit()
    db.refresh(payout)
    return {
        "id": payout.id,
        "vendor_id": payout.vendor_id,
        "vendor_name": vendor.name,
        "amount": payout.amount,
        "note": payout.note,
        "created_at": payout.created_at,
    }


# ---------- promo codes ----------
@router.get("/promo-codes", response_model=list[schemas.PromoCodeOut])
def list_promos(db: Session = Depends(get_db), admin: models.User = Depends(_admin)):
    return list(
        db.scalars(select(models.PromoCode).order_by(models.PromoCode.created_at.desc())).all()
    )


@router.post("/promo-codes", response_model=schemas.PromoCodeOut, status_code=201)
def create_promo(
    payload: schemas.PromoCodeCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    existing = db.scalar(
        select(models.PromoCode).where(models.PromoCode.code == payload.code)
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail=f"Promo code '{payload.code}' already exists")
    promo = models.PromoCode(
        code=payload.code,
        percent_off=payload.percent_off,
        max_uses=payload.max_uses,
        expires_at=payload.expires_at,
        active=payload.active,
    )
    db.add(promo)
    db.flush()  # assign promo.id so the audit row can reference it
    log_admin_action(
        db, admin, "promo_create", "promo", promo.id,
        {"code": promo.code, "percent_off": promo.percent_off},
    )
    db.commit()
    db.refresh(promo)
    return promo


@router.patch("/promo-codes/{promo_id}", response_model=schemas.PromoCodeOut)
def update_promo(
    promo_id: int,
    payload: schemas.PromoCodeUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    promo = db.get(models.PromoCode, promo_id)
    if promo is None:
        raise HTTPException(status_code=404, detail="Promo code not found")
    data = payload.model_dump(exclude_unset=True)
    changed: dict = {}
    if "code" in data and data["code"] != promo.code:
        clash = db.scalar(
            select(models.PromoCode).where(models.PromoCode.code == data["code"])
        )
        if clash is not None:
            raise HTTPException(status_code=400, detail=f"Promo code '{data['code']}' already exists")
        changed["code"] = {"from": promo.code, "to": data["code"]}
        promo.code = data["code"]
    for field in ("percent_off", "max_uses", "expires_at", "active"):
        if field in data:
            old = getattr(promo, field)
            if old != data[field]:
                # expires_at is a datetime — not JSON-serializable, so the
                # audit details store its ISO string (log_admin_action does
                # a plain json.dumps).
                changed[field] = {
                    "from": old.isoformat() if isinstance(old, dt.datetime) else old,
                    "to": data[field].isoformat()
                    if isinstance(data[field], dt.datetime) else data[field],
                }
            setattr(promo, field, data[field])
    if changed:
        log_admin_action(db, admin, "promo_update", "promo", promo.id, changed)
    db.commit()
    db.refresh(promo)
    return promo


@router.delete("/promo-codes/{promo_id}", status_code=204)
def delete_promo(
    promo_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    promo = db.get(models.PromoCode, promo_id)
    if promo is None:
        raise HTTPException(status_code=404, detail="Promo code not found")
    log_admin_action(db, admin, "promo_delete", "promo", promo_id, {"code": promo.code})
    db.delete(promo)
    db.commit()
    return None


# ---------- vendor applications ----------
@router.get("/applications", response_model=list[schemas.VendorApplicationOut])
def list_applications(
    status: str | None = Query(default=None, max_length=20),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    stmt = select(models.VendorApplication).order_by(
        models.VendorApplication.created_at.desc()
    )
    if status:
        stmt = stmt.where(models.VendorApplication.status == status.strip().lower())
    return list(db.scalars(stmt).all())


@router.patch("/applications/{application_id}", response_model=schemas.VendorApplicationOut)
def triage_application(
    application_id: int,
    payload: schemas.ApplicationStatusUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Approve or decline a vendor application.

    Approve: creates a Vendor record with is_paused=True (invisible/blocked
    at checkout until the admin finishes setup). Decline: just sets status.

    MANUAL STEP (not automated): the new vendor has no owner login. The admin
    must create a user account for the vendor and set the vendor's owner_id
    (e.g. via the backend shell or seed data), fill in the shop details/hours,
    and only then unpause the shop (PATCH /api/vendors/{id} is_paused=false).
    """
    app = db.get(models.VendorApplication, application_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if payload.status == "approved" and app.status != "approved":
        vendor = models.Vendor(
            name=app.name,
            phone=app.phone,
            city=app.city,
            area=app.city,
            is_paused=True,
        )
        db.add(vendor)
        db.flush()
    app.status = payload.status
    db.commit()
    db.refresh(app)
    return app


# ---------- loyalty points ----------
@router.get("/loyalty/stats", response_model=schemas.LoyaltyStatsOut)
def loyalty_stats(db: Session = Depends(get_db), admin: models.User = Depends(_admin)):
    """Totals across the loyalty ledger: earned, redeemed, and outstanding."""
    earned = (
        db.scalar(
            select(func.coalesce(func.sum(models.LoyaltyLedger.delta), 0)).where(
                models.LoyaltyLedger.reason == loyalty.EARN
            )
        )
        or 0
    )
    redeemed = (
        db.scalar(
            select(func.coalesce(func.sum(-models.LoyaltyLedger.delta), 0)).where(
                models.LoyaltyLedger.reason == loyalty.REDEEM
            )
        )
        or 0
    )
    outstanding = (
        db.scalar(select(func.coalesce(func.sum(models.User.points_balance), 0))) or 0
    )
    return schemas.LoyaltyStatsOut(
        total_earned=int(earned),
        total_redeemed=int(redeemed),
        total_outstanding=int(outstanding),
    )


@router.post("/loyalty/adjust", status_code=201)
def loyalty_adjust(
    payload: schemas.LoyaltyAdjustIn,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Manually adjust a customer's points balance (reason='adjust').

    delta > 0 credits points, delta < 0 debits them (never below zero).
    """
    if payload.delta == 0:
        raise HTTPException(status_code=400, detail="delta must not be zero")
    user = db.get(models.User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # Atomic balance update (DBA P1-2): the old read-modify-write lost
    # concurrent updates (two completions both read 100, both add 10,
    # both write 110). The WHERE guard keeps the balance >= 0; rowcount
    # 0 means the balance dropped below this debit concurrently.
    result = db.execute(
        update(models.User)
        .where(
            models.User.id == user.id,
            func.coalesce(models.User.points_balance, 0) + payload.delta >= 0,
        )
        .values(points_balance=func.coalesce(models.User.points_balance, 0) + payload.delta)
    )
    if result.rowcount != 1:
        db.refresh(user)  # fresh balance for an accurate message
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient points — {user.name or user.email} has "
            f"{user.points_balance or 0} points",
        )
    db.refresh(user)  # re-read the post-update balance
    db.add(
        models.LoyaltyLedger(
            user_id=user.id,
            order_id=None,
            delta=payload.delta,
            reason=loyalty.ADJUST,
            note=payload.note or f"Manual adjustment by {admin.name}",
        )
    )
    log_admin_action(
        db, admin, "loyalty_adjust", "user", user.id,
        {"delta": payload.delta, "balance": user.points_balance, "note": payload.note},
    )
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "balance": user.points_balance}


@router.get("/loyalty/reconcile")
def loyalty_reconcile(
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Read-only safety net (DBA P1-2): compare every user's cached
    points_balance against the sum of their LoyaltyLedger rows. A
    mismatch means a lost update happened somewhere — the ledger is the
    source of truth. Returns the mismatched users (empty = healthy)."""
    mismatches = loyalty.reconcile_points_balances(db)
    return {"mismatches": mismatches, "count": len(mismatches)}


@router.get("/loyalty/settings", response_model=schemas.LoyaltyRatesOut)
def loyalty_settings_get(
    db: Session = Depends(get_db), admin: models.User = Depends(_admin)
):
    out = schemas.LoyaltyRatesOut(
        points_per_dollar=loyalty.get_setting(db, "points_per_dollar", 1),
        points_per_dollar_redeem=loyalty.get_setting(db, "points_per_dollar_redeem", 50),
    )
    db.commit()  # persist the lazy-seeded default rows, if any
    return out


@router.put("/loyalty/settings", response_model=schemas.LoyaltyRatesOut)
def loyalty_settings_put(
    payload: schemas.LoyaltySettingsIn,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Update the loyalty rates. Each provided value must be a positive int."""
    for key in ("points_per_dollar", "points_per_dollar_redeem"):
        value = getattr(payload, key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise HTTPException(
                status_code=400, detail=f"{key} must be a positive integer"
            )
        loyalty.set_setting(db, key, value)
    db.commit()
    return schemas.LoyaltyRatesOut(
        points_per_dollar=loyalty.get_setting(db, "points_per_dollar", 1),
        points_per_dollar_redeem=loyalty.get_setting(db, "points_per_dollar_redeem", 50),
    )


# ---------- catering inbox ----------
def _catering_out(r: models.CateringRequest) -> schemas.CateringOut:
    return schemas.CateringOut.model_validate(r)


@router.get("/catering", response_model=list[schemas.CateringOut])
def catering_list(
    status: str | None = Query(default=None, max_length=20),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Catering inquiries, newest first. Optional ?status=new|contacted|closed."""
    stmt = select(models.CateringRequest).order_by(
        models.CateringRequest.created_at.desc(), models.CateringRequest.id.desc()
    )
    if status:
        status = status.strip().lower()
        if status not in schemas.CATERING_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"status must be one of {schemas.CATERING_STATUSES}",
            )
        stmt = stmt.where(models.CateringRequest.status == status)
    return [_catering_out(r) for r in db.scalars(stmt).all()]


@router.get("/catering/{request_id}", response_model=schemas.CateringOut)
def catering_detail(
    request_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    r = db.get(models.CateringRequest, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Catering request not found")
    return _catering_out(r)


@router.patch("/catering/{request_id}", response_model=schemas.CateringOut)
def catering_update(
    request_id: int,
    payload: schemas.CateringUpdateIn,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Update a catering inquiry: any status transition is allowed (inbox)."""
    r = db.get(models.CateringRequest, request_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Catering request not found")
    if payload.status is not None:
        r.status = payload.status
    if payload.admin_notes is not None:
        r.admin_notes = (payload.admin_notes or "").strip() or None
    db.commit()
    db.refresh(r)
    return _catering_out(r)


@router.post("/uploads/sweep-orphans")
def sweep_orphans(
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Delete uploaded dish-photo files that no dish references.

    Disk hygiene for the photo-upload endpoint (P1-3, 2026-10-15 audit):
    uploads never attached to a dish are otherwise never cleaned up.
    Only UUID-named image files are candidates; returns deletion counts.
    """
    return sweep_orphan_uploads(db)


# ---------- admin order detail (item 1) ----------
@router.get("/orders/{order_id}", response_model=schemas.AdminOrderDetailOut)
def admin_order_detail(
    order_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_staff),
):
    """Admin-only order detail: the order + its event timeline + its
    customer↔vendor message thread. The customer/vendor getters 403 for
    admin by design — this route is the admin's way in."""
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    events = list(
        db.scalars(
            select(models.OrderEvent)
            .where(models.OrderEvent.order_id == order.id)
            .order_by(models.OrderEvent.created_at, models.OrderEvent.id)
        ).all()
    )
    messages = list(
        db.scalars(
            select(models.OrderMessage)
            .where(models.OrderMessage.order_id == order.id)
            .order_by(models.OrderMessage.created_at, models.OrderMessage.id)
        ).all()
    )
    return {
        "order": _serialize(order),
        "events": [schemas.OrderEventOut.model_validate(e) for e in events],
        "messages": [schemas.OrderMessageOut.model_validate(m) for m in messages],
    }


# ---------- standalone refund (v40 rework) ----------
@router.post("/orders/{order_id}/refund")
def admin_refund(
    order_id: int,
    payload: schemas.RefundIn,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Standalone admin refund: full or partial amount via Stripe, WITHOUT
    changing the order status.

    v40 semantics:
    - Validates: order exists, order paid, amount > 0 and ≤ order total.
    - Idempotent: refunded_amount (cumulative, on the order) + new amount
      may never exceed the order total — a second identical request 400s.
    - Stripe MUST be configured (STRIPE_SECRET_KEY); otherwise a clear 400
      ("Stripe not configured") — the old silent "manual" fallback is gone
      from this endpoint. Settle off-system refunds via the payouts ledger.
    - The Stripe call itself is wrapped: a Stripe failure returns a 502
      with the reason (and logs a FAILED refund event, excluded from the
      cumulative guard) — the request never crashes with a 500.
    """
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order.paid:
        raise HTTPException(status_code=400, detail="Order is not paid — nothing to refund")
    amount = Decimal(str(payload.amount))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Refund amount must be greater than 0")
    total = Decimal(str(order.total))
    if amount > total:
        raise HTTPException(
            status_code=400,
            detail=f"Refund amount exceeds the order total (${float(total):.2f})",
        )
    already = Decimal(str(order.refunded_amount or 0))
    if already + amount > total:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Already refunded ${float(already):.2f} of "
                f"${float(total):.2f} — this refund would exceed the order total"
            ),
        )
    stripe = _stripe_client()
    if stripe is None:
        raise HTTPException(
            status_code=400,
            detail="Stripe not configured — set STRIPE_SECRET_KEY to issue card refunds",
        )
    try:
        pi_id = _stripe_payment_intent_id(db, order, stripe)
    except Exception as exc:  # noqa: BLE001 — Stripe lookup failure, not a crash
        print(f"[admin] refund payment-intent lookup failed: {exc}")
        pi_id = None
    if not pi_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe payment found on this order — cannot issue a card refund",
        )
    try:
        refund = stripe.Refund.create(
            payment_intent=pi_id, amount=int((amount * 100).to_integral_value()),
            # SECURITY fix (v40 P2): idempotency key stops a double-click /
            # concurrent retry from issuing the refund twice at Stripe.
            idempotency_key=f"refund-{order.id}-{int((amount * 100).to_integral_value())}",
        )
    except Exception as exc:  # noqa: BLE001 — Stripe failure, never a 500
        print(f"[admin] stripe refund failed: {exc}")
        _log_event(
            db, order, "refund",
            f"Admin Stripe refund of ${float(amount):.2f} FAILED — {str(exc)[:150]}",
            {"amount": float(amount), "admin_id": admin.id, "error": str(exc)[:200]},
        )
        db.commit()  # persist the FAILED event (excluded from the guard)
        raise HTTPException(
            status_code=502,
            detail=f"Stripe refund failed: {str(exc)[:200]}",
        )
    refund_id = refund.get("id") if hasattr(refund, "get") else None
    order.refunded_amount = float(already + amount)
    _log_event(
        db, order, "refund",
        f"Admin Stripe refund issued: {refund_id} for ${float(amount):.2f}",
        {"refund_id": refund_id, "amount": float(amount),
         "admin_id": admin.id, "refunded_total": float(already + amount)},
    )
    log_admin_action(
        db, admin, "refund", "order", order.id,
        {"amount": float(amount), "refund_id": refund_id,
         "refunded_total": float(already + amount)},
    )
    db.commit()
    db.refresh(order)
    return {
        "order_id": order.id,
        "refunded": float(amount),
        "refunded_total": float(already + amount),
        "result": "issued",
        "refund_id": refund_id,
    }


# ---------- vendor controls (item 3) ----------
@router.patch("/vendors/{vendor_id}")
def admin_vendor_update(
    vendor_id: int,
    payload: schemas.AdminVendorUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin-only vendor edit: pause/resume + profile fields (name,
    tagline, area, phone). The vendor-owner PATCH /vendors/{id} is
    untouched — this is the admin's separate route. No vendor delete
    (order history)."""
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    updates = payload.model_dump(exclude_unset=True)
    changed: dict = {}
    for key, value in updates.items():
        if key in ("name", "tagline", "area", "phone"):
            # name: empty → 400 below. tagline/area/phone are NOT NULL in
            # the DB — store "" (matching the vendor-owner PATCH), never
            # None, or the commit 500s on a NOT NULL violation (QA B-1).
            value = (value or "").strip()
            if key == "name" and not value:
                raise HTTPException(status_code=400, detail="Vendor name cannot be empty")
        old = getattr(vendor, key)
        if old != value:
            changed[key] = {"from": old, "to": value}
            setattr(vendor, key, value)
    log_admin_action(
        db, admin, "vendor_update", "vendor", vendor.id, changed,
    )
    db.commit()
    db.refresh(vendor)
    return {
        "id": vendor.id, "name": vendor.name, "tagline": vendor.tagline,
        "area": vendor.area, "phone": vendor.phone, "is_paused": vendor.is_paused,
    }


# ---------- dish moderation (item 4) ----------
@router.get("/dishes", response_model=list[schemas.DishOut])
def admin_dishes(
    vendor_id: int | None = Query(default=None),
    hidden_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_staff),
):
    """Admin dish list (all dishes incl. hidden) for the moderation view."""
    stmt = select(models.Dish).order_by(models.Dish.vendor_id, models.Dish.name)
    if vendor_id is not None:
        stmt = stmt.where(models.Dish.vendor_id == vendor_id)
    if hidden_only:
        stmt = stmt.where(models.Dish.is_hidden == True)  # noqa: E712
    dishes = list(db.scalars(stmt).all())
    _attach_ratings(db, dishes)
    _attach_options(db, dishes)
    _attach_ingredient_options(db, dishes)
    return dishes


@router.patch("/dishes/{dish_id}", response_model=schemas.DishOut)
def admin_dish_update(
    dish_id: int,
    payload: schemas.AdminDishUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin dish moderation: hide/unhide (is_hidden) + available toggle.
    is_hidden is SEPARATE from the vendor's `available` flag — a vendor
    cannot un-hide a moderated dish."""
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    updates = payload.model_dump(exclude_unset=True)
    changed: dict = {}
    for key, value in updates.items():
        old = getattr(dish, key)
        if old != value:
            changed[key] = {"from": old, "to": value}
            setattr(dish, key, value)
    log_admin_action(db, admin, "dish_update", "dish", dish.id, changed)
    db.commit()
    db.refresh(dish)
    _attach_ratings(db, [dish])
    _attach_options(db, [dish])
    _attach_ingredient_options(db, [dish])
    return dish


@router.delete("/dishes/{dish_id}")
def admin_dish_delete(
    dish_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin-only dish delete, honoring the same 'can't delete if on any
    order' rule as the vendor delete (dish + options + ingredients)."""
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    if db.scalar(
        select(func.count())
        .select_from(models.OrderItem)
        .where(models.OrderItem.dish_id == dish.id)
    ):
        raise HTTPException(
            status_code=400,
            detail="This dish can't be deleted because it's on existing orders. Hide it instead.",
        )
    # History that references the dish: favorites, reviews, and stock
    # movements all FK-reference dishes with no cascade. On Postgres the
    # DELETE would 500 with an IntegrityError (SQLite's FK enforcement
    # being off hid this in dev — DBA P0-3). Block with the same
    # hide-instead message as the orders rule.
    blockers = []
    for model, label in (
        (models.Favorite, "favorited"),
        (models.Review, "reviewed"),
        (models.StockMovement, "has stock history"),
    ):
        if db.scalar(
            select(func.count()).select_from(model).where(model.dish_id == dish.id)
        ):
            blockers.append(label)
    if blockers:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This dish can't be deleted because it {', '.join(blockers)} "
                "— hide it instead."
            ),
        )
    # Options + ingredients cascade via Dish.options / Dish.dish_ingredients
    # (cascade="all, delete-orphan") — same as the vendor delete.
    db.delete(dish)
    log_admin_action(db, admin, "dish_delete", "dish", dish_id, {"name": dish.name})
    db.commit()
    return {"deleted": dish_id}


# ---------- review moderation (v40: moderation queue) ----------
@router.get("/reviews")
def admin_reviews(
    status: str | None = Query(default=None, pattern="^(pending|approved|hidden)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin review moderation queue: PENDING first, then newest.
    Optional ?status=pending|approved|hidden filter."""
    # Pending-first ordering: a CASE puts pending (0) before approved (1)
    # before hidden (2); newest first within each bucket.
    stmt = (
        select(models.Review)
        .order_by(
            sa_case(
                (models.Review.status == "pending", 0),
                (models.Review.status == "approved", 1),
                else_=2,
            ),
            models.Review.created_at.desc(),
            models.Review.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    if status:
        stmt = stmt.where(models.Review.status == status)
    rows = []
    for r in db.scalars(stmt).all():
        dish = db.get(models.Dish, r.dish_id)
        author = db.get(models.User, r.user_id)
        rows.append({
            "id": r.id,
            "dish_id": r.dish_id,
            "dish_name": dish.name if dish else None,
            "vendor_id": dish.vendor_id if dish else None,
            "user_id": r.user_id,
            "author_name": author.name if author else None,
            "rating": r.rating,
            "text": r.text,
            "photo_urls": r.photo_urls,
            "status": r.status,
            "created_at": r.created_at,
        })
    return rows


@router.patch("/reviews/{review_id}")
def admin_review_moderate(
    review_id: int,
    payload: schemas.ReviewStatusUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """v40: approve / hide / re-pend a review. Audit-logged. Approved
    reviews are the only ones the public ever sees."""
    review = db.get(models.Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    before = review.status or "pending"
    if before != payload.status:
        review.status = payload.status
        log_admin_action(
            db, admin, "review_moderate", "review", review.id,
            {"from": before, "to": payload.status},
        )
        db.commit()
        db.refresh(review)
    return {"id": review.id, "status": review.status}


@router.delete("/reviews/{review_id}")
def admin_review_delete(
    review_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin-only review delete (hard delete). Reviews don't require a
    completed order, so fake reviews must be removable by the admin."""
    review = db.get(models.Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    log_admin_action(
        db, admin, "review_delete", "review", review_id,
        {"dish_id": review.dish_id, "user_id": review.user_id, "rating": review.rating},
    )
    db.delete(review)
    db.commit()
    return {"deleted": review_id}


# ---------- user management (item 6) ----------
@router.get("/users", response_model=list[schemas.AdminUserOut])
def admin_users(
    role: str | None = Query(default=None, pattern="^(customer|vendor|admin|staff)$"),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin user list: optional role filter + name/email search."""
    stmt = select(models.User).order_by(models.User.created_at.desc(), models.User.id.desc())
    if role:
        stmt = stmt.where(models.User.role == role)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(models.User.name).like(needle),
                func.lower(models.User.email).like(needle),
            )
        )
    return list(db.scalars(stmt.offset(offset).limit(limit)).all())


# === v40: create staff (or other) accounts, admin-only ===
@router.post("/users", response_model=schemas.AdminUserOut, status_code=201)
def admin_user_create(
    payload: schemas.AdminUserCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Create an account (default role: staff). Password is hashed
    server-side (bcrypt); the plaintext never leaves this request.
    Duplicate emails are rejected with 409."""
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    existing = db.scalar(select(models.User).where(models.User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = models.User(
        email=email,
        name=payload.name.strip(),
        hashed_password=auth.hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.flush()
    log_admin_action(db, admin, "user_create", "user", user.id,
                     {"role": user.role, "email": user.email})
    db.commit()
    db.refresh(user)
    return user
# === END v40 ===
@router.patch("/users/{user_id}", response_model=schemas.AdminUserOut)
def admin_user_update(
    user_id: int,
    payload: schemas.AdminUserUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin user edit: change role, deactivate/reactivate (is_active).
    Deactivate only — never delete users (order history). An admin may
    not deactivate or demote themselves."""
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        if payload.is_active is False:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
        if payload.role is not None and payload.role != "admin":
            raise HTTPException(status_code=400, detail="You cannot demote your own account")
    updates = payload.model_dump(exclude_unset=True)
    changed: dict = {}
    for key, value in updates.items():
        old = getattr(user, key)
        if old != value:
            changed[key] = {"from": old, "to": value}
            setattr(user, key, value)
    log_admin_action(db, admin, "user_update", "user", user.id, changed)
    db.commit()
    db.refresh(user)
    return user


# ---------- site settings (item 7) ----------
@router.get("/settings", response_model=schemas.SiteSettingsOut)
def settings_get(
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Site settings from the Setting key-value table (missing keys fall
    back to defaults). commission_percent is the live global default
    commission rate — used for vendors whose own commission_rate is NULL."""
    values: dict[str, str] = dict(_SETTING_DEFAULTS)
    for row in db.scalars(
        select(models.Setting).where(models.Setting.key.in_(list(_SETTING_DEFAULTS)))
    ):
        values[row.key] = row.value
    return {
        "tax_rate": Decimal(values["tax_rate"]),
        "commission_percent": Decimal(values["commission_percent"]),
        "site_name": values["site_name"],
        # v40: alert toggles stored as "1"/"0" strings.
        "alert_orders": values["alert_orders"] == "1",
        "alert_applications": values["alert_applications"] == "1",
        "alert_tickets": values["alert_tickets"] == "1",
        "alert_phone": values["alert_phone"],
        "last_backup_at": values["last_backup_at"],
    }


@router.put("/settings", response_model=schemas.SiteSettingsOut)
def settings_put(
    payload: schemas.SiteSettingsIn,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Update site settings. tax_rate takes effect on the NEXT checkout
    (orders read the stored rate at checkout time)."""
    updates = payload.model_dump(exclude_unset=True)
    changed: dict = {}
    for key, value in updates.items():
        # v40: store alert-toggle booleans as "1"/"0" strings like the
        # rest of the key-value table.
        if isinstance(value, bool):
            text = "1" if value else "0"
        else:
            text = str(value).strip() if key == "site_name" else str(value)
        if key == "site_name" and not text:
            raise HTTPException(status_code=400, detail="site_name cannot be empty")
        row = db.scalar(select(models.Setting).where(models.Setting.key == key))
        if row is None:
            db.add(models.Setting(key=key, value=text))
            changed[key] = {"from": None, "to": text}
        elif row.value != text:
            changed[key] = {"from": row.value, "to": text}
            row.value = text
    if changed:
        log_admin_action(db, admin, "settings_update", "settings", None, changed)
    db.commit()
    return settings_get(db, admin)


# ---------- audit log (item 9) ----------
@router.get("/audit-log")
def audit_log(
    action: str | None = Query(default=None, max_length=60),
    admin_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin audit log: paginated, filterable by action and admin."""
    stmt = select(models.AdminAuditLog).order_by(
        models.AdminAuditLog.created_at.desc(), models.AdminAuditLog.id.desc()
    )
    if action:
        stmt = stmt.where(models.AdminAuditLog.action == action.strip())
    if admin_id is not None:
        stmt = stmt.where(models.AdminAuditLog.admin_user_id == admin_id)
    rows = list(db.scalars(stmt.offset(offset).limit(limit)).all())
    names = {
        u.id: u.name
        for u in db.scalars(
            select(models.User).where(
                models.User.id.in_({r.admin_user_id for r in rows if r.admin_user_id})
            )
        )
    }
    total = db.scalar(select(func.count()).select_from(models.AdminAuditLog))
    return {"items": [_audit_row(r, names.get(r.admin_user_id)) for r in rows], "total": total}


# === F6 (Oct 2026): report-a-problem — admin problem-reports list + status changer ===
def _problem_out(p: models.OrderProblem, db: Session) -> schemas.OrderProblemOut:
    order = db.get(models.Order, p.order_id)
    dish_name = None
    if p.order_item_id:
        item = db.get(models.OrderItem, p.order_item_id)
        dish_name = item.dish_name if item else None
    vendor_name = order.vendor.name if order and order.vendor else None
    customer = db.get(models.User, p.customer_id)
    return schemas.OrderProblemOut(
        id=p.id,
        order_id=p.order_id,
        order_item_id=p.order_item_id,
        category=p.category,
        description=p.description,
        photo_url=p.photo_url,
        desired_outcome=p.desired_outcome,
        status=p.status,
        created_at=p.created_at,
        dish_name=dish_name,
        vendor_name=vendor_name,
        customer_name=customer.name if customer else None,
    )


@router.get("/problem-reports", response_model=list[schemas.OrderProblemOut])
def problem_reports(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_staff),
):
    """All customer problem reports, newest first, filterable by status."""
    stmt = select(models.OrderProblem).order_by(
        models.OrderProblem.created_at.desc(), models.OrderProblem.id.desc()
    )
    if status:
        stmt = stmt.where(models.OrderProblem.status == status.strip().lower())
    return [_problem_out(p, db) for p in db.scalars(stmt).all()]


@router.patch("/problem-reports/{problem_id}", response_model=schemas.OrderProblemOut)
def problem_report_status(
    problem_id: int,
    payload: schemas.OrderProblemStatusUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_staff),
):
    """Status changer: new -> in_review -> resolved. Audit-logged."""
    problem = db.get(models.OrderProblem, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem report not found")
    before = problem.status
    if before != payload.status:
        problem.status = payload.status
        log_admin_action(
            db,
            admin,
            "problem_report_status",
            "order_problem",
            problem.id,
            {"from": before, "to": payload.status},
        )
        db.commit()
        db.refresh(problem)
    return _problem_out(problem, db)


# === v29: reorder-nudge broadcast (Oct 2026) ===
@router.post("/nudges/send")
def send_nudges(
    dry_run: bool = Query(default=False),
    max_per_user: int = Query(default=3, ge=1),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Push reorder nudges to eligible users that have push tokens.

    Eligible = >= 2 distinct past orders of a dish, most recent >= 21 days
    ago (see routers/nudges.py). Per-user sends are capped at max_per_user
    (default 3), most-overdue dishes first. ?dry_run=true reports what WOULD
    be sent under the cap without sending anything. The in-app send works
    regardless of hosting; for scheduled sending add a cron/APScheduler entry
    that POSTs here (see UPGRADE.md — hosting is on hold).
    """
    from .nudges import NUDGE_MIN_DAYS, NUDGE_MIN_ORDERS, eligible_nudges, nudge_copy_for

    users = list(
        db.scalars(
            select(models.User).where(
                models.User.role == "customer",
                models.User.is_active.is_not(False),
            )
        ).all()
    )
    sent = 0
    users_notified = 0
    details: list[dict] = []
    for user in users:
        tokens = list(
            db.scalars(
                select(models.PushToken).where(models.PushToken.user_id == user.id)
            ).all()
        )
        if not tokens:
            continue
        # Cap per user (most overdue first — eligible_nudges is already sorted).
        nudges = eligible_nudges(db, user)[:max_per_user]
        if not nudges:
            continue
        per_user_sent = 0
        for nudge in nudges:
            title, body = nudge_copy_for(nudge)
            data = {
                "type": "reorder_nudge",
                "dish_id": nudge["dish_id"],
                "vendor_id": nudge["vendor_id"],
            }
            if dry_run:
                per_user_sent += 1
                continue
            if notifier.send_push_to_tokens(db, tokens, title, body, data=data):
                per_user_sent += 1
        if per_user_sent:
            users_notified += 1
            sent += per_user_sent
            details.append(
                {
                    "user_id": user.id,
                    "email": user.email,
                    "nudges": per_user_sent,
                    "dish_ids": [n["dish_id"] for n in nudges],
                }
            )
    if not dry_run:
        log_admin_action(
            db,
            admin,
            "nudges_send",
            "nudge",
            None,
            {"users_notified": users_notified, "pushes_sent": sent},
        )
        db.commit()
    return {
        "dry_run": dry_run,
        "criteria": {
            "min_distinct_orders": NUDGE_MIN_ORDERS,
            "min_days_since_last": NUDGE_MIN_DAYS,
            "max_per_user": max_per_user,
        },
        "users_notified": users_notified,
        "pushes_sent": sent,
        "details": details,
    }
# === END v29 ===


# === v40: broadcast announcements (admin -> customers) ===
BROADCAST_DAILY_LIMIT = 5


def _broadcast_audience_users(db: Session, audience: str, vendor_id: int | None) -> list[int]:
    """User ids that should receive a broadcast: every customer for
    audience "all", or customers who ordered from the vendor."""
    if audience == "vendor" and vendor_id:
        return list(
            db.scalars(
                select(models.Order.customer_id)
                .where(
                    models.Order.vendor_id == vendor_id,
                    models.Order.customer_id.isnot(None),
                )
                .distinct()
            ).all()
        )
    return list(
        db.scalars(
            select(models.User.id).where(models.User.role == "customer")
        ).all()
    )


@router.get("/broadcasts", response_model=list[schemas.BroadcastOut])
def broadcasts_list(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Admin broadcast history: audience + timestamp, newest first."""
    rows = db.scalars(
        select(models.Broadcast)
        .order_by(models.Broadcast.created_at.desc(), models.Broadcast.id.desc())
        .limit(limit)
    ).all()
    out = []
    for b in rows:
        vendor_name = None
        if b.vendor_id:
            v = db.get(models.Vendor, b.vendor_id)
            vendor_name = v.name if v else None
        out.append(
            schemas.BroadcastOut(
                id=b.id,
                title_en=b.title_en,
                title_ar=b.title_ar,
                body_en=b.body_en,
                body_ar=b.body_ar,
                audience=b.audience,
                vendor_id=b.vendor_id,
                vendor_name=vendor_name,
                push_sent=b.push_sent,
                created_at=b.created_at,
            )
        )
    return out


@router.post("/broadcasts", response_model=schemas.BroadcastOut, status_code=201)
def broadcast_send(
    payload: schemas.BroadcastIn,
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Send one broadcast (EN+AR) to all customers or one vendor's
    customers. Delivery: Expo push + the in-app announcements feed.
    Rate-limited to 5/day (anti-spam). Every broadcast is recorded with
    audience + timestamp. Never crashes — a push failure still records
    the broadcast (push_sent stays 0).
    """
    # Rate limit: max BROADCAST_DAILY_LIMIT per rolling 24h.
    day_ago = dt.datetime.utcnow() - dt.timedelta(hours=24)
    sent_today = db.scalar(
        select(func.count())
        .select_from(models.Broadcast)
        .where(models.Broadcast.created_at >= day_ago)
    ) or 0
    if sent_today >= BROADCAST_DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Broadcast limit reached ({BROADCAST_DAILY_LIMIT}/day) — try again tomorrow",
        )
    vendor = None
    if payload.audience == "vendor":
        if not payload.vendor_id:
            raise HTTPException(
                status_code=400, detail="vendor_id is required for vendor-audience broadcasts"
            )
        vendor = db.get(models.Vendor, payload.vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found")
    b = models.Broadcast(
        title_en=payload.title_en.strip(),
        title_ar=payload.title_ar.strip(),
        body_en=payload.body_en.strip(),
        body_ar=payload.body_ar.strip(),
        audience=payload.audience,
        vendor_id=payload.vendor_id if payload.audience == "vendor" else None,
        created_by=admin.id,
    )
    db.add(b)
    db.flush()
    # Expo push to the audience (best effort — never breaks the request).
    push_sent = 0
    try:
        user_ids = _broadcast_audience_users(db, payload.audience, payload.vendor_id)
        if user_ids:
            rows = (
                db.query(models.PushToken)
                .filter(models.PushToken.user_id.in_(user_ids))
                .all()
            )
            title = f"{payload.title_en.strip()} / {payload.title_ar.strip()}"
            body = f"{payload.body_en.strip()}\n{payload.body_ar.strip()}"
            if notifier.send_push_to_tokens(
                db, rows, title, body, data={"broadcastId": b.id}
            ):
                push_sent = len({r.user_id for r in rows if getattr(r, "expo_token", None)})
    except Exception as exc:  # noqa: BLE001
        print(f"[admin] broadcast push failed: {exc}")
    b.push_sent = push_sent
    log_admin_action(
        db, admin, "broadcast", "broadcast", b.id,
        {"audience": b.audience, "vendor_id": b.vendor_id, "push_sent": push_sent},
    )
    db.commit()
    db.refresh(b)
    return schemas.BroadcastOut(
        id=b.id,
        title_en=b.title_en,
        title_ar=b.title_ar,
        body_en=b.body_en,
        body_ar=b.body_ar,
        audience=b.audience,
        vendor_id=b.vendor_id,
        vendor_name=vendor.name if vendor else None,
        push_sent=b.push_sent,
        created_at=b.created_at,
    )
# === END v40 ===


# === v40: one-click CSV exports (Excel-compatible) ===
def _parse_export_range(
    from_date: str | None, to_date: str | None
) -> tuple[dt.datetime | None, dt.datetime | None]:
    """Parse ?from=YYYY-MM-DD&to=YYYY-MM-DD into an inclusive datetime
    range. 400 on bad input."""
    start = end = None
    try:
        if from_date:
            start = dt.datetime.strptime(from_date, "%Y-%m-%d")
        if to_date:
            end = dt.datetime.strptime(to_date, "%Y-%m-%d") + dt.timedelta(days=1)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Dates must be YYYY-MM-DD (e.g. ?from=2026-10-01&to=2026-10-31)"
        )
    return start, end


def _csv_response(filename: str, header: list[str], rows: list[list]) -> StreamingResponse:
    """Build an Excel-compatible CSV download (UTF-8 with BOM so Excel
    renders Arabic correctly). Streams from memory — fine for the
    marketplace's data volume."""
    import csv
    import io

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM: Excel opens UTF-8 (incl. Arabic) correctly
    def _safe(v):
        # SECURITY fix (v40 P1-2): neutralize CSV formula injection — a cell
        # starting with = + - @ (or tab/CR) executes in Excel. Prefix "'".
        # Names/notes are free text (future vendors are untrusted input).
        if v is None:
            return ""
        s = v if isinstance(v, str) else str(v)
        if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + s
        return v
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe(v) for v in row])
    data = buf.getvalue().encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/orders")
def export_orders_csv(
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_dl),
):
    """Download orders as CSV (admin-only). Optional ?from=&to= (YYYY-MM-DD)."""
    start, end = _parse_export_range(from_date, to_date)
    stmt = (
        select(models.Order)
        .options(joinedload(models.Order.customer), joinedload(models.Order.vendor))
        .order_by(models.Order.created_at.desc(), models.Order.id.desc())
    )
    if start:
        stmt = stmt.where(models.Order.created_at >= start)
    if end:
        stmt = stmt.where(models.Order.created_at < end)
    rows = []
    for o in db.scalars(stmt).unique().all():
        rows.append([
            o.id,
            o.created_at.isoformat() if o.created_at else "",
            o.status,
            o.vendor.name if o.vendor else "",
            o.customer.name if o.customer else (o.guest_name or "guest"),
            o.customer.email if o.customer else "",
            o.fulfillment,
            o.payment_method,
            "yes" if o.paid else "no",
            float(o.subtotal or 0),
            float(o.delivery_fee or 0),
            float(o.tax or 0),
            float(o.discount_amount or 0),
            float(o.total or 0),
            float(o.refunded_amount or 0),
        ])
    log_admin_action(db, admin, "export", "orders", None,
                     {"from": from_date, "to": to_date, "rows": len(rows)})
    db.commit()
    return _csv_response(
        "orders.csv",
        ["id", "created_at", "status", "vendor", "customer", "customer_email",
         "fulfillment", "payment_method", "paid", "subtotal", "delivery_fee",
         "tax", "discount", "total", "refunded"],
        rows,
    )


@router.get("/export/payouts")
def export_payouts_csv(
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_dl),
):
    """Download the vendor payout ledger as CSV (admin-only)."""
    start, end = _parse_export_range(from_date, to_date)
    stmt = (
        select(models.VendorPayout)
        .options(joinedload(models.VendorPayout.vendor))
        .order_by(models.VendorPayout.created_at.desc(), models.VendorPayout.id.desc())
    )
    if start:
        stmt = stmt.where(models.VendorPayout.created_at >= start)
    if end:
        stmt = stmt.where(models.VendorPayout.created_at < end)
    rows = []
    for p in db.scalars(stmt).unique().all():
        rows.append([
            p.id,
            p.created_at.isoformat() if p.created_at else "",
            p.vendor.name if p.vendor else "",
            float(p.amount or 0),
            p.note or "",
        ])
    log_admin_action(db, admin, "export", "payouts", None,
                     {"from": from_date, "to": to_date, "rows": len(rows)})
    db.commit()
    return _csv_response(
        "payouts.csv",
        ["id", "created_at", "vendor", "amount", "note"],
        rows,
    )


@router.get("/export/customers")
def export_customers_csv(
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_dl),
):
    """Download customers as CSV (admin-only). Date filter applies to
    the customer's signup date."""
    start, end = _parse_export_range(from_date, to_date)
    stmt = select(models.User).where(models.User.role == "customer").order_by(
        models.User.created_at.desc(), models.User.id.desc()
    )
    if start:
        stmt = stmt.where(models.User.created_at >= start)
    if end:
        stmt = stmt.where(models.User.created_at < end)
    rows = []
    for u in db.scalars(stmt).all():
        spent = db.scalar(
            select(func.coalesce(func.sum(models.Order.total), 0)).where(
                models.Order.customer_id == u.id,
                models.Order.status != "cancelled",
            )
        ) or 0
        n_orders = db.scalar(
            select(func.count()).select_from(models.Order).where(
                models.Order.customer_id == u.id,
                models.Order.status != "cancelled",
            )
        ) or 0
        rows.append([
            u.id,
            u.created_at.isoformat() if u.created_at else "",
            u.name or "",
            u.email or "",
            u.phone or "",
            int(n_orders),
            float(spent),
            int(u.points_balance or 0),
        ])
    log_admin_action(db, admin, "export", "customers", None,
                     {"from": from_date, "to": to_date, "rows": len(rows)})
    db.commit()
    return _csv_response(
        "customers.csv",
        ["id", "signed_up", "name", "email", "phone", "orders", "total_spent", "loyalty_points"],
        rows,
    )
# === END v40 ===


# === v40: one-tap database backup ===
@router.get("/backup")
def download_backup(
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin_dl),
):
    """Download a full database backup in one tap (admin-only).

    SQLite dev path (current): streams a .sql text dump produced by the
    stdlib sqlite3 iterdump() — restore with `sqlite3 app.db < backup.sql`.
    Records the backup time in the last_backup_at setting (shown in the
    Settings tab).

    Postgres prod variant (when DATABASE_URL is Postgres): replace the
    dump body with a pg_dump subprocess call, e.g.
        pg_dump "$DATABASE_URL" --no-owner
    streamed the same way; everything else (timestamp, audit log,
    admin-only guard) stays identical.
    """
    import io
    import sqlite3

    url = str(engine.url)
    if url.startswith("sqlite"):
        # Resolve the SQLite file path from the SQLAlchemy URL.
        db_path = url.split(":///", 1)[1] if ":///" in url else ":memory:"
        if db_path == ":memory:":
            raise HTTPException(status_code=400, detail="Cannot back up an in-memory database")
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"marketplace-backup-{stamp}.sql"
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            dump_text = "\n".join(src.iterdump())
        finally:
            src.close()
        data = dump_text.encode("utf-8")
        # Record the backup timestamp (shown in the Settings tab).
        row = db.scalar(select(models.Setting).where(models.Setting.key == "last_backup_at"))
        now_iso = dt.datetime.now().isoformat(timespec="seconds")
        if row is None:
            db.add(models.Setting(key="last_backup_at", value=now_iso))
        else:
            row.value = now_iso
        log_admin_action(db, admin, "backup", "database", None,
                         {"filename": filename, "bytes": len(data)})
        db.commit()
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/sql",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    raise HTTPException(
        status_code=400,
        detail="Automatic backup is wired for the SQLite dev path — use pg_dump for Postgres",
    )
# === END v40 ===


# === v40: vendor scorecards ===
@router.get("/scorecards")
def vendor_scorecards(
    db: Session = Depends(get_db),
    admin: models.User = Depends(_admin),
):
    """Per-vendor scorecard (admin-only, read-only): avg rating (approved
    reviews), total/completed/cancelled orders, cancellation rate, avg
    prep time vs the vendor's quoted prep_minutes, and avg response time
    (order placed → first status change). Flags: cancellation rate > 10%
    or rating < 3.5. Timings come from the order_events log; orders with
    no usable events are skipped for that metric (never counted as 0).
    """
    vendors = list(db.scalars(select(models.Vendor).order_by(models.Vendor.name)).all())
    out = []
    for v in vendors:
        total = db.scalar(
            select(func.count()).select_from(models.Order).where(models.Order.vendor_id == v.id)
        ) or 0
        completed = db.scalar(
            select(func.count()).select_from(models.Order).where(
                models.Order.vendor_id == v.id, models.Order.status == "completed")
        ) or 0
        cancelled = db.scalar(
            select(func.count()).select_from(models.Order).where(
                models.Order.vendor_id == v.id, models.Order.status == "cancelled")
        ) or 0
        cancel_rate = round(cancelled / total * 100, 1) if total else 0.0
        avg_rating = db.scalar(
            select(func.avg(models.Review.rating)).where(
                models.Review.vendor_id == v.id, models.Review.status == "approved")
        )
        avg_rating = round(float(avg_rating), 2) if avg_rating is not None else None
        n_ratings = db.scalar(
            select(func.count()).select_from(models.Review).where(
                models.Review.vendor_id == v.id, models.Review.status == "approved")
        ) or 0
        # Timings from the event log (naive UTC datetimes throughout).
        order_ids = list(
            db.scalars(
                select(models.Order.id).where(models.Order.vendor_id == v.id)
            ).all()
        )
        prep_minutes_list: list[float] = []
        response_minutes_list: list[float] = []
        if order_ids:
            created_map = dict(
                db.execute(
                    select(models.Order.id, models.Order.created_at).where(
                        models.Order.id.in_(order_ids))
                ).all()
            )
            ev_rows = db.execute(
                select(
                    models.OrderEvent.order_id,
                    models.OrderEvent.meta,
                    models.OrderEvent.created_at,
                ).where(
                    models.OrderEvent.order_id.in_(order_ids),
                    models.OrderEvent.event_type == "status",
                )
            ).all()
            first_change: dict[int, dt.datetime] = {}
            ready_at: dict[int, dt.datetime] = {}
            for oid, meta, ts in ev_rows:
                try:
                    to_status = (json.loads(meta) if meta else {}).get("to")
                except (ValueError, TypeError):
                    continue
                if oid not in first_change and to_status not in (None, "new"):
                    first_change[oid] = ts
                if to_status in ("ready", "completed") and oid not in ready_at:
                    ready_at[oid] = ts
            for oid, placed in created_map.items():
                if placed is None:
                    continue
                if oid in first_change:
                    delta = (first_change[oid] - placed).total_seconds() / 60
                    if 0 <= delta < 60 * 24 * 7:  # sanity: ignore clock-skew outliers
                        response_minutes_list.append(delta)
                if oid in ready_at:
                    delta = (ready_at[oid] - placed).total_seconds() / 60
                    if 0 <= delta < 60 * 24 * 7:
                        prep_minutes_list.append(delta)
        avg_response = (
            round(sum(response_minutes_list) / len(response_minutes_list), 1)
            if response_minutes_list else None
        )
        avg_prep = (
            round(sum(prep_minutes_list) / len(prep_minutes_list), 1)
            if prep_minutes_list else None
        )
        quoted = v.prep_minutes
        flags: list[str] = []
        if cancel_rate > 10:
            flags.append("high_cancellation")
        if avg_rating is not None and avg_rating < 3.5:
            flags.append("low_rating")
        out.append({
            "vendor_id": v.id,
            "vendor_name": v.name,
            "is_paused": v.is_paused,
            "avg_rating": avg_rating,
            "rating_count": int(n_ratings),
            "total_orders": int(total),
            "completed_orders": int(completed),
            "cancelled_orders": int(cancelled),
            "cancellation_rate": cancel_rate,
            "avg_response_minutes": avg_response,
            "avg_prep_minutes": avg_prep,
            "quoted_prep_minutes": quoted,
            "flags": flags,
        })
    # Flagged vendors first, then by name.
    out.sort(key=lambda r: (0 if r["flags"] else 1, r["vendor_name"].lower()))
    return out
# === END v40 ===
