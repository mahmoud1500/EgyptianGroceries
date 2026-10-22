"""Vendor routes: public listing/storefront + vendor-only earnings/settings/reports."""
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, schemas
from ..commission import commission_due_for_order
from ..database import get_db
from ..photo_uploads import delete_uploaded_file

router = APIRouter(prefix="/api/vendors", tags=["vendors"])

_MARKET_TZ = ZoneInfo("America/Los_Angeles")
_DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def _parse_hhmm(value: str | None) -> tuple[int, int] | None:
    """Parse an "HH:MM" string into (hour, minute); None when unusable."""
    if not value:
        return None
    try:
        h_s, m_s = value.strip().split(":")
        if len(h_s) != 2 or len(m_s) != 2:
            return None
        h, m = int(h_s), int(m_s)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        return None
    return None


def _fmt_time(h: int, m: int) -> str:
    """24h "HH:MM" -> friendly "10:00 AM"."""
    suffix = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{m:02d} {suffix}"


def _parse_weekdays(value: str | None) -> set[int]:
    """closed_weekdays ("5" or "5,6") -> weekday ints (0=Sunday..6=Saturday)."""
    days: set[int] = set()
    for part in (value or "").split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 6:
            days.add(int(part))
    return days


def vendor_open_status(
    vendor: models.Vendor, now: dt.datetime | None = None
) -> tuple[bool, str]:
    """Is this vendor open right now? Returns (is_open, message).

    The marketplace operates in Pacific time. Use it explicitly so server
    hosting location and customer timezone cannot change shop-hours behavior.
    A vendor with no hours configured is always open.
    """
    name = vendor.name or "This shop"
    if vendor.is_paused:
        return False, f"{name} is temporarily paused — please check back soon."
    now = now or dt.datetime.now(_MARKET_TZ)
    now = (
        now.replace(tzinfo=_MARKET_TZ)
        if now.tzinfo is None
        else now.astimezone(_MARKET_TZ)
    )
    weekday = (now.weekday() + 1) % 7  # 0=Sunday .. 6=Saturday
    closed = _parse_weekdays(vendor.closed_weekdays)
    open_t = _parse_hhmm(vendor.open_time)
    close_t = _parse_hhmm(vendor.close_time)

    def _next_open_phrase(from_day: int) -> str:
        for i in range(1, 8):
            d = (from_day + i) % 7
            if d not in closed:
                when = "tomorrow" if i == 1 else f"on {_DAY_NAMES[d]}"
                if open_t:
                    return f"{when} at {_fmt_time(*open_t)}"
                return when
        return "soon"  # all 7 days closed — degenerate config

    if weekday in closed:
        return False, f"{name} is closed today — opens {_next_open_phrase(weekday)}."
    if open_t and close_t:
        now_min = now.hour * 60 + now.minute
        o = open_t[0] * 60 + open_t[1]
        c = close_t[0] * 60 + close_t[1]
        if c > o:  # same-day window, e.g. 09:00–21:00
            is_open = o <= now_min < c
        else:  # overnight window, e.g. 18:00–02:00
            is_open = now_min >= o or now_min < c
        if is_open:
            return True, f"{name} is open now — closes at {_fmt_time(*close_t)}."
        if c > o and now_min < o:
            return False, f"{name} is closed right now — opens at {_fmt_time(*open_t)}."
        # Past closing time: point at the next day they actually open.
        return False, f"{name} is closed for today — opens {_next_open_phrase(weekday)}."
    return True, f"{name} is open now."


@router.get("", response_model=list[schemas.VendorOut])
def list_vendors(db: Session = Depends(get_db)):
    vendors = list(db.scalars(select(models.Vendor).order_by(models.Vendor.name)).all())
    if vendors:
        vids = [v.id for v in vendors]
        ragg = {
            vid: (cnt, float(avg or 0))
            for vid, cnt, avg in db.execute(
                select(
                    models.Review.vendor_id,
                    func.count(models.Review.id),
                    func.avg(models.Review.rating),
                )
                .where(models.Review.vendor_id.in_(vids))
                .group_by(models.Review.vendor_id)
            ).all()
        }
        dagg = {
            vid: cnt
            for vid, cnt in db.execute(
                select(models.Dish.vendor_id, func.count(models.Dish.id))
                .where(models.Dish.vendor_id.in_(vids), models.Dish.available == True)  # noqa: E712
                .group_by(models.Dish.vendor_id)
            ).all()
        }
        for v in vendors:
            cnt, avg = ragg.get(v.id, (0, 0.0))
            v.avg_rating = round(avg, 1)
            v.rating_count = int(cnt)
            v.dish_count = int(dagg.get(v.id, 0))
    return vendors


@router.get("/mine", response_model=list[schemas.VendorOut])
def my_vendors(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    return list(
        db.scalars(select(models.Vendor).where(models.Vendor.owner_id == user.id).order_by(models.Vendor.name)).all()
    )


@router.get("/mine/payouts")
def my_payouts(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Read-only payout history for the vendor's OWN shops only."""
    owned_ids = [v.id for v in user.vendors]
    if not owned_ids:
        return []
    rows = list(
        db.execute(
            select(models.VendorPayout, models.Vendor.name)
            .join(models.Vendor, models.Vendor.id == models.VendorPayout.vendor_id)
            .where(models.VendorPayout.vendor_id.in_(owned_ids))
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


@router.get("/mine/commission-receivables")
def my_commission_receivables(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Read-only weekly commission balance for shops owned by this vendor."""
    owned_ids = [v.id for v in user.vendors]
    if not owned_ids:
        return []
    rate_row = db.scalar(select(models.Setting).where(models.Setting.key == "commission_percent"))
    try:
        default_rate = Decimal(str(rate_row.value)) if rate_row is not None else Decimal("0")
    except (ValueError, TypeError):
        default_rate = Decimal("0")
    vendors = list(db.scalars(select(models.Vendor).where(models.Vendor.id.in_(owned_ids))))
    collected_rows = db.execute(
        select(
            models.VendorSettlement.vendor_id,
            func.coalesce(func.sum(models.VendorSettlement.amount), 0),
        )
        .where(
            models.VendorSettlement.vendor_id.in_(owned_ids),
            models.VendorSettlement.source == "commission_collection",
        )
        .group_by(models.VendorSettlement.vendor_id)
    ).all()
    collected_by_vendor = {int(v_id): Decimal(str(amount or 0)) for v_id, amount in collected_rows}
    result = []
    for vendor in vendors:
        orders = list(db.scalars(
            select(models.Order).where(
                models.Order.vendor_id == vendor.id,
                models.Order.status == "completed",
                func.lower(models.Order.payment_method) == "cash",
            )
        ))
        due = sum((commission_due_for_order(order, vendor, default_rate) for order in orders), Decimal("0.00")).quantize(Decimal("0.01"))
        collected = collected_by_vendor.get(vendor.id, Decimal("0.00"))
        result.append({
            "vendor_id": vendor.id,
            "vendor_name": vendor.name,
            "cash_order_count": len(orders),
            "commission_due": float(due),
            "commission_collected": float(collected),
            "outstanding_commission": float(max(Decimal("0.00"), due - collected)),
        })
    return result

@router.get("/mine/settlements")
def my_settlements(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Read-only money-movement history for shops owned by the logged-in vendor."""
    owned_ids = [v.id for v in user.vendors]
    if not owned_ids:
        return []
    rows = db.execute(
        select(models.VendorSettlement, models.Vendor.name)
        .join(models.Vendor, models.Vendor.id == models.VendorSettlement.vendor_id)
        .where(models.VendorSettlement.vendor_id.in_(owned_ids))
        .order_by(models.VendorSettlement.created_at.desc(), models.VendorSettlement.id.desc())
    ).all()
    return [
        {
            "id": s.id, "vendor_id": s.vendor_id, "vendor_name": name,
            "order_id": s.order_id, "source": s.source, "amount": float(s.amount),
            "method": s.method, "note": s.note,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s, name in rows
    ]


@router.get("/mine/reviews")
def my_reviews(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """v40: reviews on the vendor's OWN shops — INCLUDING pending and
    hidden (read-only; moderation is admin-only). The public
    /api/vendors/{id}/reviews shows approved only."""
    owned_ids = [v.id for v in user.vendors]
    if not owned_ids:
        return {"reviews": [], "count": 0}
    rows = list(
        db.scalars(
            select(models.Review)
            .options(joinedload(models.Review.user))
            .where(models.Review.vendor_id.in_(owned_ids))
            .order_by(models.Review.created_at.desc(), models.Review.id.desc())
        ).all()
    )
    out = []
    for r in rows:
        dish = db.get(models.Dish, r.dish_id) if r.dish_id else None
        item = schemas.ReviewOut.model_validate(r)
        item.user_name = r.user.name if r.user else ""
        d = item.model_dump()
        d["dish_name"] = dish.name if dish else None
        out.append(d)
    return {"reviews": out, "count": len(out)}


@router.get("/{vendor_id}/open-status")
def open_status(vendor_id: int, db: Session = Depends(get_db)):
    """Public: is this shop open right now? -> {open: bool, message: str}."""
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    is_open, message = vendor_open_status(vendor)
    return {"open": is_open, "message": message}


# === Community drops / neighborhood batch delivery (Oct 2026) ===
def _vendor_for(user: models.User, vendor_id: int, db: Session) -> models.Vendor:
    """Scope a vendor id to the calling vendor (403 unless they own it)."""
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return auth.vendor_owned_by(vendor, user)


def _drop_zips(drop: models.DeliveryDrop) -> list[str]:
    """CSV zip_codes -> normalized 5-digit list (same style as delivery_zips)."""
    return [z.strip() for z in (drop.zip_codes or "").split(",") if z.strip()]


def _serialize_drop_order(order: models.Order) -> schemas.OrderOut:
    # Same shape as the vendor's order list (mirrors orders._serialize).
    if order.points_discount is None:
        order.points_discount = Decimal("0")
    out = schemas.OrderOut.model_validate(order)
    out.customer_name = order.customer.name if order.customer else (order.guest_name or "")
    out.vendor_name = order.vendor.name if order.vendor else ""
    return out


@router.get("/{vendor_id}/drops", response_model=list[schemas.DropOut])
def list_drops(
    vendor_id: int,
    zip: str | None = Query(default=None, description="Public filter: customer ZIP"),
    db: Session = Depends(get_db),
    caller: models.User | None = Depends(auth.get_optional_user),
):
    """Two modes on one path:

    - ?zip=XXXXX → PUBLIC, no auth: the vendor's ACTIVE drops with
      drop_date >= today whose zip_codes cover the ZIP, ordered by date.
    - no zip → the vendor's OWN management view (all drops, incl. past and
      inactive): require_vendor + ownership scoping.
    """
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if zip is not None:
        # === public drop picker ===
        z = zip.strip()
        if not (z.isascii() and z.isdigit() and len(z) == 5):
            raise HTTPException(status_code=422, detail="ZIP code must be 5 digits")
        rows = list(
            db.scalars(
                select(models.DeliveryDrop)
                .where(
                    models.DeliveryDrop.vendor_id == vendor_id,
                    models.DeliveryDrop.is_active == True,  # noqa: E712
                    models.DeliveryDrop.drop_date >= dt.date.today(),
                )
                .order_by(models.DeliveryDrop.drop_date, models.DeliveryDrop.time_start)
            ).all()
        )
        return [d for d in rows if z in _drop_zips(d)]
    # === vendor management view ===
    if caller is None or caller.role != "vendor":
        raise HTTPException(status_code=403, detail="Vendor account required")
    _vendor_for(caller, vendor_id, db)
    return list(
        db.scalars(
            select(models.DeliveryDrop)
            .where(models.DeliveryDrop.vendor_id == vendor_id)
            .order_by(models.DeliveryDrop.drop_date.desc(), models.DeliveryDrop.id.desc())
        ).all()
    )


@router.post("/{vendor_id}/drops", response_model=schemas.DropOut, status_code=201)
def create_drop(
    vendor_id: int,
    payload: schemas.DropIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    _vendor_for(user, vendor_id, db)
    drop = models.DeliveryDrop(vendor_id=vendor_id, **payload.model_dump())
    db.add(drop)
    db.commit()
    db.refresh(drop)
    return drop


@router.patch("/{vendor_id}/drops/{drop_id}", response_model=schemas.DropOut)
def update_drop(
    vendor_id: int,
    drop_id: int,
    payload: schemas.DropUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    _vendor_for(user, vendor_id, db)
    drop = db.get(models.DeliveryDrop, drop_id)
    if drop is None or drop.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="Drop not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(drop, field, value)
    db.commit()
    db.refresh(drop)
    return drop


@router.delete("/{vendor_id}/drops/{drop_id}")
def delete_drop(
    vendor_id: int,
    drop_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    _vendor_for(user, vendor_id, db)
    drop = db.get(models.DeliveryDrop, drop_id)
    if drop is None or drop.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="Drop not found")
    # Detach orders first (drop_id -> NULL); the denormalized drop_label
    # stays on each order so past orders keep reading correctly.
    db.query(models.Order).filter(models.Order.drop_id == drop.id).update(
        {"drop_id": None}, synchronize_session=False
    )
    db.delete(drop)
    db.commit()
    return {"ok": True}


@router.get("/{vendor_id}/drops/{drop_id}/orders")
def drop_orders(
    vendor_id: int,
    drop_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """The drop's batch: orders riding this drop, newest first, plus the count."""
    _vendor_for(user, vendor_id, db)
    drop = db.get(models.DeliveryDrop, drop_id)
    if drop is None or drop.vendor_id != vendor_id:
        raise HTTPException(status_code=404, detail="Drop not found")
    orders = list(
        db.scalars(
            select(models.Order)
            .where(models.Order.drop_id == drop_id)
            .order_by(models.Order.created_at.desc(), models.Order.id.desc())
        ).all()
    )
    return {"count": len(orders), "orders": [_serialize_drop_order(o) for o in orders]}
# === END community drops ===


@router.get("/{vendor_id}", response_model=schemas.VendorOut)
def get_vendor(vendor_id: int, db: Session = Depends(get_db)):
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor


@router.get("/{vendor_id}/earnings", response_model=schemas.EarningsOut)
def vendor_earnings(
    vendor_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    auth.vendor_owned_by(vendor, user)
    revenue = db.scalar(
        select(func.coalesce(func.sum(models.Order.total), 0)).where(
            models.Order.vendor_id == vendor_id,
            models.Order.status != "cancelled",
        )
    )
    count = db.scalar(
        select(func.count()).where(
            models.Order.vendor_id == vendor_id,
            models.Order.status != "cancelled",
        )
    )
    return {"vendor_id": vendor_id, "total_revenue": Decimal(revenue), "order_count": int(count)}


@router.get("/{vendor_id}/my", response_model=schemas.VendorOut)
def my_vendor(
    vendor_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    auth.vendor_owned_by(vendor, user)
    return vendor


@router.patch("/{vendor_id}", response_model=schemas.VendorOut)
def update_vendor(
    vendor_id: int,
    payload: schemas.VendorUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    auth.vendor_owned_by(vendor, user)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        vendor.name = data["name"].strip()
    for field in ("tagline", "area", "phone"):
        if field in data:
            setattr(vendor, field, (data[field] or "").strip())
    # Zelle/Venmo handles: where customers send this vendor's payments.
    for field in ("zelle_handle", "venmo_handle"):
        if field in data:
            setattr(vendor, field, (data[field] or "").strip() or None)
    for field in ("street_address", "apt", "city", "state", "zipcode"):
        if field in data:
            setattr(vendor, field, (data[field] or "").strip() or None)
    if "fulfillment" in data and data["fulfillment"] is not None:
        vendor.fulfillment = data["fulfillment"]
    if "delivery_fee" in data and data["delivery_fee"] is not None:
        vendor.delivery_fee = data["delivery_fee"]
    # === v46: free-delivery threshold. Unlike delivery_fee, an explicit
    # null CLEARS the threshold (feature off) — the key being present in
    # the payload is the signal. Bounds (>= 0) are enforced by the schema. ===
    if "free_delivery_over" in data:
        vendor.free_delivery_over = data["free_delivery_over"]
    # === END v46 ===
    # === v29: delivery zones + chef intro profile (Oct 2026) ===
    if "delivery_zips" in data:
        # Already validated + normalized by the schema (blank -> None =
        # pickup only); assign as-is.
        vendor.delivery_zips = data["delivery_zips"]
    if "intro_video_url" in data:
        old_intro = vendor.intro_video_url
        vendor.intro_video_url = (data["intro_video_url"] or "").strip() or None
        if vendor.intro_video_url != old_intro:
            delete_uploaded_file(old_intro)  # replaced video: don't orphan the file
    if "chef_name" in data:
        vendor.chef_name = (data["chef_name"] or "").strip() or None
    if "chef_photo_url" in data:
        vendor.chef_photo_url = (data["chef_photo_url"] or "").strip() or None
    for field in ("chef_bio", "chef_bio_ar"):
        if field in data:
            setattr(vendor, field, (data[field] or "").strip() or None)
    # === END v29 ===
    # Shop hours + pause switch (Oct 2026). PATCH /api/vendors/{id} already
    # exists — this confirms it accepts is_paused (and the hours fields).
    if "is_paused" in data and data["is_paused"] is not None:
        vendor.is_paused = bool(data["is_paused"])
    if "prep_minutes" in data and data["prep_minutes"] is not None:
        vendor.prep_minutes = data["prep_minutes"]
    for field in ("open_time", "close_time", "closed_weekdays"):
        if field in data:
            setattr(vendor, field, (data[field] or "").strip() or None)
    # === FEATURE 9: pickup-point card — editable in store settings ===
    for field in ("pickup_address", "pickup_map_url", "pickup_instructions"):
        if field in data:
            setattr(vendor, field, (data[field] or "").strip() or None)
    # === END FEATURE 9 ===
    db.commit()
    db.refresh(vendor)
    return vendor


@router.get("/{vendor_id}/reports/summary", response_model=schemas.ReportSummary)
def report_summary(
    vendor_id: int,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    auth.vendor_owned_by(vendor, user)

    # created_at is stored in UTC (server_default=func.now()), so bucket days in
    # UTC too — using the local date here silently dropped "today's" orders
    # every evening in US timezones.
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=days - 1)
    orders = list(
        db.scalars(
            select(models.Order)
            .options(joinedload(models.Order.items))
            .where(
                models.Order.vendor_id == vendor_id,
                func.date(models.Order.created_at) >= start.isoformat(),
            )
        ).unique().all()
    )

    per_day = [
        {"date": (start + dt.timedelta(days=i)).isoformat(), "revenue": 0.0, "orders": 0}
        for i in range(days)
    ]
    by_status: dict[str, int] = {}
    dish_agg: dict[int, dict] = {}
    for o in orders:
        by_status[o.status] = by_status.get(o.status, 0) + 1
        if o.status == "cancelled":
            continue  # revenue counts non-cancelled orders only
        day_key = o.created_at.date().isoformat() if o.created_at else None
        idx = next((i for i, d in enumerate(per_day) if d["date"] == day_key), None)
        if idx is not None:
            per_day[idx]["revenue"] += float(o.total)
            per_day[idx]["orders"] += 1
        for item in o.items:
            agg = dish_agg.setdefault(
                item.dish_id, {"dish_id": item.dish_id, "name": item.dish_name, "qty": 0, "revenue": 0.0}
            )
            agg["qty"] += item.quantity
            agg["revenue"] += float(item.unit_price) * item.quantity

    for d in per_day:
        d["revenue"] = round(d["revenue"], 2)
    top_dishes = sorted(dish_agg.values(), key=lambda a: a["qty"], reverse=True)[:5]
    for t in top_dishes:
        t["revenue"] = round(t["revenue"], 2)

    return {
        "per_day": per_day,
        "by_status": by_status,
        "top_dishes": top_dishes,
    }
