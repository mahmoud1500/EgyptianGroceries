"""Favorite routes: customers save dishes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, schemas
from ..database import get_db
from .dishes import _attach_ingredient_options, _attach_options, _attach_ratings

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


def _require_customer(user: models.User) -> models.User:
    if user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can use favorites")
    return user


@router.get("", response_model=list[schemas.DishOut])
def list_favorites(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _require_customer(user)
    rows = list(
        db.scalars(
            select(models.Favorite)
            .options(joinedload(models.Favorite.dish))
            .where(models.Favorite.user_id == user.id)
            .order_by(models.Favorite.created_at.desc())
        ).all()
    )
    return [f.dish for f in rows if f.dish is not None]


@router.post("", response_model=schemas.FavoriteOut, status_code=201)
def add_favorite(
    payload: schemas.FavoriteCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _require_customer(user)
    dish = db.get(models.Dish, payload.dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    existing = db.scalar(
        select(models.Favorite).where(
            models.Favorite.user_id == user.id,
            models.Favorite.dish_id == payload.dish_id,
        )
    )
    if existing is not None:
        return existing  # idempotent: already favorited
    fav = models.Favorite(user_id=user.id, dish_id=payload.dish_id)
    db.add(fav)
    db.commit()
    db.refresh(fav)
    return fav


@router.delete("/{dish_id}", status_code=204)
def remove_favorite(
    dish_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    _require_customer(user)
    fav = db.scalar(
        select(models.Favorite).where(
            models.Favorite.user_id == user.id,
            models.Favorite.dish_id == dish_id,
        )
    )
    if fav is None:
        raise HTTPException(status_code=404, detail="Not in favorites")
    db.delete(fav)
    db.commit()
    return None


# === F3 (Oct 2026): one-tap reorder — toggle + your usuals ===
@router.post("/toggle", response_model=schemas.FavoriteToggleOut)
def toggle_favorite(
    payload: schemas.FavoriteCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """One-call heart toggle for dish cards (mobile app + web)."""
    _require_customer(user)
    dish = db.get(models.Dish, payload.dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    existing = db.scalar(
        select(models.Favorite).where(
            models.Favorite.user_id == user.id,
            models.Favorite.dish_id == payload.dish_id,
        )
    )
    if existing is not None:
        db.delete(existing)
        db.commit()
        return schemas.FavoriteToggleOut(dish_id=payload.dish_id, favorited=False)
    db.add(models.Favorite(user_id=user.id, dish_id=payload.dish_id))
    db.commit()
    return schemas.FavoriteToggleOut(dish_id=payload.dish_id, favorited=True)


@router.get("/usuals", response_model=list[schemas.DishOut])
def my_usuals(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """'Your usuals': the customer's most-ordered dishes (top 8 by total
    quantity, non-cancelled orders), for one-tap reorder. Only dishes that
    are still orderable (available + not admin-hidden) are returned."""
    _require_customer(user)
    rows = db.execute(
        select(models.Dish, func.coalesce(func.sum(models.OrderItem.quantity), 0).label("n"))
        .join(models.OrderItem, models.OrderItem.dish_id == models.Dish.id)
        .join(models.Order, models.Order.id == models.OrderItem.order_id)
        .where(
            models.Order.customer_id == user.id,
            models.Order.status != "cancelled",
            models.Dish.available == True,  # noqa: E712
            models.Dish.is_hidden == False,  # noqa: E712
        )
        .group_by(models.Dish.id)
        .order_by(func.coalesce(func.sum(models.OrderItem.quantity), 0).desc())
        .limit(8)
    ).all()
    dishes = [r[0] for r in rows]
    _attach_ratings(db, dishes)
    _attach_options(db, dishes)
    _attach_ingredient_options(db, dishes)
    return dishes
