"""Customer-owned saved delivery addresses.

Each address is scoped to the authenticated user. Orders continue to store a
separate delivery_address snapshot, so editing/deleting a saved address never
rewrites historical orders.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/addresses", tags=["customer addresses"])


def _customer(user: models.User) -> None:
    if user.role != "customer":
        raise HTTPException(status_code=403, detail="Customer account required")


def _owned_address(db: Session, user: models.User, address_id: int) -> models.CustomerAddress:
    address = db.scalar(
        select(models.CustomerAddress).where(
            models.CustomerAddress.id == address_id,
            models.CustomerAddress.user_id == user.id,
        )
    )
    if address is None:
        raise HTTPException(status_code=404, detail="Saved address not found")
    return address


def _unset_defaults(db: Session, user_id: int, except_id: int | None = None) -> None:
    stmt = update(models.CustomerAddress).where(
        models.CustomerAddress.user_id == user_id,
        models.CustomerAddress.is_default.is_(True),
    )
    if except_id is not None:
        stmt = stmt.where(models.CustomerAddress.id != except_id)
    db.execute(stmt.values(is_default=False))


@router.get("", response_model=list[schemas.CustomerAddressOut])
def list_addresses(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _customer(user)
    return list(db.scalars(
        select(models.CustomerAddress)
        .where(models.CustomerAddress.user_id == user.id)
        .order_by(models.CustomerAddress.is_default.desc(), models.CustomerAddress.id.asc())
    ).all())


@router.post("", response_model=schemas.CustomerAddressOut, status_code=status.HTTP_201_CREATED)
def create_address(
    payload: schemas.CustomerAddressIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _customer(user)
    count = db.scalar(
        select(models.CustomerAddress.id).where(models.CustomerAddress.user_id == user.id).limit(1)
    )
    if count is None:
        make_default = True
    else:
        make_default = payload.is_default
    if make_default:
        _unset_defaults(db, user.id)
    address = models.CustomerAddress(
        user_id=user.id,
        label=payload.label,
        recipient_name=payload.recipient_name,
        phone=payload.phone,
        street_address=payload.street_address,
        apt=payload.apt,
        city=payload.city,
        state=payload.state,
        zipcode=payload.zipcode,
        instructions=payload.instructions,
        is_default=make_default,
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.put("/{address_id}", response_model=schemas.CustomerAddressOut)
def update_address(
    address_id: int,
    payload: schemas.CustomerAddressIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _customer(user)
    address = _owned_address(db, user, address_id)
    if payload.is_default:
        _unset_defaults(db, user.id, except_id=address.id)
    for field in (
        "label", "recipient_name", "phone", "street_address", "apt",
        "city", "state", "zipcode", "instructions",
    ):
        setattr(address, field, getattr(payload, field))
    address.is_default = payload.is_default
    if not address.is_default:
        has_default = db.scalar(
            select(models.CustomerAddress.id).where(
                models.CustomerAddress.user_id == user.id,
                models.CustomerAddress.is_default.is_(True),
                models.CustomerAddress.id != address.id,
            ).limit(1)
        )
        if has_default is None:
            address.is_default = True
    db.commit()
    db.refresh(address)
    return address


@router.post("/{address_id}/default", response_model=schemas.CustomerAddressOut)
def set_default_address(
    address_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _customer(user)
    address = _owned_address(db, user, address_id)
    _unset_defaults(db, user.id, except_id=address.id)
    address.is_default = True
    db.commit()
    db.refresh(address)
    return address


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(
    address_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _customer(user)
    address = _owned_address(db, user, address_id)
    was_default = address.is_default
    db.delete(address)
    db.flush()
    if was_default:
        replacement = db.scalar(
            select(models.CustomerAddress)
            .where(models.CustomerAddress.user_id == user.id)
            .order_by(models.CustomerAddress.id.asc())
            .limit(1)
        )
        if replacement is not None:
            replacement.is_default = True
    db.commit()
    return None
