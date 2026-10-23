"""FEATURE 5 — vendor combo meals (family bundles).

Customer: list bundles per vendor (+ a discoverable all-vendors listing),
one bundle detail. Vendor: create / edit / delete bundles from their OWN
menu — 3–5 dishes enforced server-side. Checkout integration lives in
routers/orders.py (_prepare_order); the bundle's fixed price is the only
price the server ever uses for a bundle line item.
"""
import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/bundles", tags=["bundles"])


def _vendor_for(user: models.User, vendor_id: int, db: Session) -> models.Vendor:
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return auth.vendor_owned_by(vendor, user)


def _la_today() -> dt.date:
    """Today in America/Los_Angeles (the shops' timezone) for order_by cutoffs."""
    try:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo("America/Los_Angeles")).date()
    except Exception:  # noqa: BLE001 — zoneinfo missing (Windows w/o tzdata)
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=-7))).date()


def _ended_flags(db: Session, bundles: list[models.Bundle]) -> dict[int, bool]:
    """ended flag per bundle id — batched so the max_orders count is one query.

    A bundle is ended when: available=false, OR its order_by cutoff is before
    today (America/Los_Angeles), OR max_orders non-cancelled orders already
    contain it.
    """
    today = _la_today()
    capped_ids = [b.id for b in bundles if b.max_orders]
    counts: dict[int, int] = {}
    if capped_ids:
        counts = {
            bid: cnt
            for bid, cnt in db.execute(
                select(
                    models.OrderItem.bundle_id,
                    func.count(distinct(models.Order.id)),
                )
                .join(models.Order, models.Order.id == models.OrderItem.order_id)
                .where(
                    models.OrderItem.bundle_id.in_(capped_ids),
                    models.Order.status != "cancelled",
                )
                .group_by(models.OrderItem.bundle_id)
            ).all()
        }
    flags: dict[int, bool] = {}
    for b in bundles:
        ended = not b.available
        if not ended and b.order_by:
            try:
                ended = dt.date.fromisoformat(b.order_by) < today
            except ValueError:
                ended = False  # validated on write; never crash the listing
        if not ended and b.max_orders:
            ended = counts.get(b.id, 0) >= b.max_orders
        flags[b.id] = ended
    return flags


def _bundle_ended(db: Session, bundle: models.Bundle) -> bool:
    """Single-bundle ended check (checkout path)."""
    return _ended_flags(db, [bundle])[bundle.id]


def _serialize(
    bundle: models.Bundle, db: Session, *, ended: bool | None = None
) -> schemas.BundleOut:
    out = schemas.BundleOut.model_validate(bundle)
    out.vendor_name = bundle.vendor.name if bundle.vendor else ""
    out.items = [
        schemas.BundleItemOut(
            id=i.id,
            dish_id=i.dish_id,
            dish_name=i.dish.name if i.dish else "",
            # v52: component dish's Arabic name for AR-mode rendering.
            dish_name_ar=i.dish.name_ar if i.dish else None,
            quantity=i.quantity,
        )
        for i in (bundle.items or [])
    ]
    out.ended = _bundle_ended(db, bundle) if ended is None else ended
    return out


def _validate_items(db: Session, vendor: models.Vendor, items: list[schemas.BundleItemIn]) -> dict[int, models.Dish]:
    """Resolve the bundle's dishes, all from the vendor's OWN menu.

    400 unless every dish exists, belongs to this vendor, and is available.
    """
    dish_ids = [i.dish_id for i in items]
    dishes = {
        d.id: d
        for d in db.scalars(
            select(models.Dish).where(models.Dish.id.in_(dish_ids))
        ).all()
    }
    for i in items:
        dish = dishes.get(i.dish_id)
        if dish is None:
            raise HTTPException(status_code=404, detail=f"Dish {i.dish_id} not found")
        if dish.vendor_id != vendor.id:
            raise HTTPException(
                status_code=400,
                detail=f"Dish '{dish.name}' does not belong to this vendor",
            )
        if not dish.available:
            raise HTTPException(
                status_code=400,
                detail=f"Dish '{dish.name}' is not available",
            )
    return dishes


@router.get("", response_model=list[schemas.BundleOut])
def list_bundles(
    vendor_id: int | None = Query(default=None),
    available_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Customer listing: bundles for one vendor, or every vendor's bundles
    (the discoverable listing) when vendor_id is omitted.

    Ended bundles (past the order_by cutoff, max_orders reached, or
    unavailable) are always excluded here — the vendor's own view is
    GET /api/bundles/mine."""
    stmt = (
        select(models.Bundle)
        .options(
            joinedload(models.Bundle.items).joinedload(models.BundleItem.dish),
            joinedload(models.Bundle.vendor),
        )
        .order_by(models.Bundle.id.desc())
    )
    if vendor_id is not None:
        stmt = stmt.where(models.Bundle.vendor_id == vendor_id)
    if available_only:
        stmt = stmt.where(models.Bundle.available.is_(True))
    bundles = list(db.scalars(stmt).unique().all())
    flags = _ended_flags(db, bundles)
    return [_serialize(b, db, ended=flags[b.id]) for b in bundles if not flags[b.id]]


@router.get("/mine", response_model=list[schemas.BundleOut])
def my_bundles(
    vendor_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Vendor view: ALL of the caller's bundles — including ended ones — with
    the `ended` flag. Pass vendor_id to scope to one shop; omitted means all
    of the caller's shops."""
    stmt = (
        select(models.Bundle)
        .options(
            joinedload(models.Bundle.items).joinedload(models.BundleItem.dish),
            joinedload(models.Bundle.vendor),
        )
        .order_by(models.Bundle.id.desc())
    )
    if vendor_id is not None:
        _vendor_for(user, vendor_id, db)
        stmt = stmt.where(models.Bundle.vendor_id == vendor_id)
    else:
        owned_ids = [v.id for v in user.vendors]
        if not owned_ids:
            return []
        stmt = stmt.where(models.Bundle.vendor_id.in_(owned_ids))
    bundles = list(db.scalars(stmt).unique().all())
    flags = _ended_flags(db, bundles)
    return [_serialize(b, db, ended=flags[b.id]) for b in bundles]


@router.get("/{bundle_id}", response_model=schemas.BundleOut)
def get_bundle(bundle_id: int, db: Session = Depends(get_db)):
    bundle = db.scalar(
        select(models.Bundle)
        .options(
            joinedload(models.Bundle.items).joinedload(models.BundleItem.dish),
            joinedload(models.Bundle.vendor),
        )
        .where(models.Bundle.id == bundle_id)
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return _serialize(bundle, db)


@router.post("", response_model=schemas.BundleOut, status_code=201)
def create_bundle(
    vendor_id: int,
    payload: schemas.BundleCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Vendor creates a bundle from 3–5 of their OWN dishes at a fixed price.

    The 3–5 count is enforced by the schema (min_length/max_length) AND
    re-checked here; dish ownership + availability are validated too.
    """
    vendor = _vendor_for(user, vendor_id, db)
    # 3–5 dishes, enforced server-side -> clean 400 on violation.
    if not (schemas.BUNDLE_MIN_DISHES <= len(payload.items) <= schemas.BUNDLE_MAX_DISHES):
        raise HTTPException(
            status_code=400,
            detail=f"A bundle needs {schemas.BUNDLE_MIN_DISHES}–{schemas.BUNDLE_MAX_DISHES} dishes",
        )
    _validate_items(db, vendor, payload.items)
    bundle = models.Bundle(
        vendor_id=vendor.id,
        name=payload.name,
        name_ar=payload.name_ar,
        description=payload.description or "",
        description_ar=payload.description_ar,
        price=Decimal(str(payload.price)),
        photo_url=payload.photo_url,
        available=payload.available,
        holiday_name=payload.holiday_name,
        order_by=payload.order_by,
        max_orders=payload.max_orders,
        items=[
            models.BundleItem(dish_id=i.dish_id, quantity=i.quantity)
            for i in payload.items
        ],
    )
    db.add(bundle)
    db.commit()
    db.refresh(bundle)
    return _serialize(bundle, db)


@router.patch("/{bundle_id}", response_model=schemas.BundleOut)
def update_bundle(
    bundle_id: int,
    payload: schemas.BundleUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    bundle = db.get(models.Bundle, bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    _vendor_for(user, bundle.vendor_id, db)
    for field in (
        "name", "name_ar", "description", "description_ar", "photo_url", "available",
        "holiday_name", "order_by", "max_orders",
    ):
        val = getattr(payload, field)
        if val is not None:
            setattr(bundle, field, val)
    if payload.price is not None:
        bundle.price = Decimal(str(payload.price))
    if payload.items is not None:
        if not (schemas.BUNDLE_MIN_DISHES <= len(payload.items) <= schemas.BUNDLE_MAX_DISHES):
            raise HTTPException(
                status_code=400,
                detail=f"A bundle needs {schemas.BUNDLE_MIN_DISHES}–{schemas.BUNDLE_MAX_DISHES} dishes",
            )
        _validate_items(db, bundle.vendor, payload.items)
        bundle.items = [
            models.BundleItem(dish_id=i.dish_id, quantity=i.quantity)
            for i in payload.items
        ]
    db.commit()
    db.refresh(bundle)
    return _serialize(bundle, db)


@router.delete("/{bundle_id}", status_code=204)
def delete_bundle(
    bundle_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    bundle = db.get(models.Bundle, bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    _vendor_for(user, bundle.vendor_id, db)
    db.delete(bundle)
    db.commit()
    return None
