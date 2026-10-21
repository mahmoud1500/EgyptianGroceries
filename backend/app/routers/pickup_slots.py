"""FEATURE 8 — vendor pickup slots (weekly pickup windows).

Vendor portal: manage weekly slots (add / edit / toggle / delete) for the
vendor's OWN shop. Customer: list a vendor's ACTIVE slots at checkout;
when a vendor has at least one active slot, pickup checkout REQUIRES
choosing one (validated server-side in routers/orders.py); vendors with no
slots keep today's behavior (no slot required).
"""
import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/pickup-slots", tags=["pickup-slots"])

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MARKET_TZ = ZoneInfo("America/Los_Angeles")


def _fmt_time(hm: str) -> str:
    """'14:00' -> '2:00 PM', '09:30' -> '9:30 AM'."""
    h, m = int(hm.split(":")[0]), int(hm.split(":")[1])
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def slot_next_date(
    slot: models.PickupSlot,
    today: dt.date | None = None,
    now: dt.datetime | None = None,
) -> dt.date:
    """Next future pickup date for this weekday, using Pacific marketplace time."""
    now = now or dt.datetime.now(_MARKET_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_MARKET_TZ)
    else:
        now = now.astimezone(_MARKET_TZ)
    today = today or now.date()
    delta = (slot.weekday - today.weekday()) % 7
    next_date = today + dt.timedelta(days=delta)
    vendor = getattr(slot, "vendor", None)
    prep_minutes = max(0, int(getattr(vendor, "prep_minutes", 0) or 0))
    earliest = now + dt.timedelta(minutes=prep_minutes)
    slot_start = dt.datetime.combine(
        next_date,
        dt.time.fromisoformat(slot.start_time),
        tzinfo=_MARKET_TZ,
    )
    if next_date == now.date() and slot_start <= earliest:
        next_date += dt.timedelta(days=7)
    return next_date


def slot_label(slot: models.PickupSlot) -> str:
    """'Friday 2:00–6:00 PM' — the stable weekly label."""
    return f"{_WEEKDAYS[slot.weekday]} {_fmt_time(slot.start_time)}–{_fmt_time(slot.end_time)}"


def slot_label_with_date(slot: models.PickupSlot, on: dt.date | None = None) -> str:
    """'Friday 2:00–6:00 PM · Oct 16' — the snapshot stored on the order."""
    d = on or slot_next_date(slot)
    return f"{slot_label(slot)} · {d.strftime('%b')} {d.day}"


def _serialize(slot: models.PickupSlot) -> schemas.PickupSlotOut:
    out = schemas.PickupSlotOut.model_validate(slot)
    out.label = slot_label(slot)
    out.next_date = slot_next_date(slot).isoformat()
    return out


def _vendor_for(user: models.User, vendor_id: int, db: Session) -> models.Vendor:
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return auth.vendor_owned_by(vendor, user)


# ---------- customer: a vendor's ACTIVE slots ----------
@router.get("/vendor/{vendor_id}", response_model=list[schemas.PickupSlotOut])
def list_vendor_slots(vendor_id: int, db: Session = Depends(get_db)):
    """Active weekly slots for one vendor — the checkout slot picker reads this."""
    slots = list(
        db.scalars(
            select(models.PickupSlot)
            .options(joinedload(models.PickupSlot.vendor))
            .where(
                models.PickupSlot.vendor_id == vendor_id,
                models.PickupSlot.active.is_(True),
            )
            .order_by(models.PickupSlot.weekday, models.PickupSlot.start_time)
        ).all()
    )
    return [_serialize(s) for s in slots]


# ---------- vendor portal: manage my shop's slots ----------
@router.get("/mine", response_model=list[schemas.PickupSlotOut])
def my_slots(
    vendor_id: int = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    _vendor_for(user, vendor_id, db)
    slots = list(
        db.scalars(
            select(models.PickupSlot)
            .options(joinedload(models.PickupSlot.vendor))
            .where(models.PickupSlot.vendor_id == vendor_id)
            .order_by(models.PickupSlot.weekday, models.PickupSlot.start_time)
        ).all()
    )
    return [_serialize(s) for s in slots]


@router.post("/mine", response_model=schemas.PickupSlotOut, status_code=201)
def create_slot(
    payload: schemas.PickupSlotCreate,
    vendor_id: int = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    _vendor_for(user, vendor_id, db)
    slot = models.PickupSlot(
        vendor_id=vendor_id,
        weekday=payload.weekday,
        start_time=payload.start_time,
        end_time=payload.end_time,
        active=payload.active,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return _serialize(slot)


@router.patch("/mine/{slot_id}", response_model=schemas.PickupSlotOut)
def update_slot(
    slot_id: int,
    payload: schemas.PickupSlotUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    slot = db.get(models.PickupSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Pickup slot not found")
    _vendor_for(user, slot.vendor_id, db)
    new_weekday = payload.weekday if payload.weekday is not None else slot.weekday
    new_start = payload.start_time if payload.start_time is not None else slot.start_time
    new_end = payload.end_time if payload.end_time is not None else slot.end_time
    if new_start >= new_end:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")
    slot.weekday = new_weekday
    slot.start_time = new_start
    slot.end_time = new_end
    if payload.active is not None:
        slot.active = payload.active
    db.commit()
    db.refresh(slot)
    return _serialize(slot)


@router.delete("/mine/{slot_id}", status_code=204)
def delete_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    slot = db.get(models.PickupSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Pickup slot not found")
    _vendor_for(user, slot.vendor_id, db)
    db.delete(slot)
    db.commit()
    return None
