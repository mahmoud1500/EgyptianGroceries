"""Review routes: customers rate dishes and/or vendors."""
import datetime as dt
import json

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, schemas
from ..database import get_db
from ..photo_uploads import save_uploaded_photo
from ..ratelimit import check_rate_limit

router = APIRouter(tags=["reviews"])

MAX_REVIEW_PHOTOS = 3


def _review_photos(review: models.Review) -> list[str]:
    """Parse the photo_urls JSON column; NULL/corrupt -> []."""
    if not review.photo_urls:
        return []
    try:
        urls = json.loads(review.photo_urls)
    except (ValueError, TypeError):
        return []
    return [u for u in (urls or []) if isinstance(u, str) and u]


def _serialize(review: models.Review) -> schemas.ReviewOut:
    out = schemas.ReviewOut.model_validate(review)
    out.user_name = review.user.name if review.user else ""
    return out


def _avg_and_count(rows: list[models.Review]) -> tuple[float, int]:
    count = len(rows)
    avg = round(sum(r.rating for r in rows) / count, 2) if count else 0.0
    return avg, count


@router.post("/api/reviews", response_model=schemas.ReviewOut, status_code=201)
def upsert_review(
    payload: schemas.ReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    if user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can leave reviews")
    check_rate_limit(request, "review_create", limit=30, window_seconds=3600)

    vendor_id = payload.vendor_id
    if payload.dish_id is not None:
        dish = db.get(models.Dish, payload.dish_id)
        if dish is None:
            raise HTTPException(status_code=404, detail="Dish not found")
        vendor_id = dish.vendor_id  # vendor is derived from the dish

    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")

    text = (payload.text or "").strip() or None

    # One review per user per dish (or per vendor for vendor-only reviews):
    # update the existing one instead of duplicating.
    stmt = select(models.Review).where(
        models.Review.user_id == user.id,
        models.Review.vendor_id == vendor_id,
    )
    if payload.dish_id is not None:
        stmt = stmt.where(models.Review.dish_id == payload.dish_id)
    else:
        stmt = stmt.where(models.Review.dish_id.is_(None))
    existing = db.scalar(stmt)
    if existing is not None:
        existing.rating = payload.rating
        existing.text = text
        db.commit()
        db.refresh(existing)
        existing.user = user
        return _serialize(existing)

    review = models.Review(
        user_id=user.id,
        dish_id=payload.dish_id,
        vendor_id=vendor_id,
        rating=payload.rating,
        text=text,
        # === v40: new reviews enter moderation as pending — not public
        # until the admin approves. ===
        status="pending",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    review.user = user
    return _serialize(review)


@router.get("/api/dishes/{dish_id}/reviews", response_model=schemas.ReviewListOut)
def dish_reviews(dish_id: int, db: Session = Depends(get_db)):
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    # === v40: public lists show approved reviews only. ===
    rows = list(
        db.scalars(
            select(models.Review)
            .options(joinedload(models.Review.user))
            .where(
                models.Review.dish_id == dish_id,
                models.Review.status == "approved",
            )
            .order_by(models.Review.created_at.desc())
        ).all()
    )
    avg, count = _avg_and_count(rows)
    return {"reviews": [_serialize(r) for r in rows], "avg_rating": avg, "count": count}


@router.get("/api/vendors/{vendor_id}/reviews", response_model=schemas.ReviewListOut)
def vendor_reviews(vendor_id: int, db: Session = Depends(get_db)):
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    # === v40: public lists show approved reviews only. ===
    rows = list(
        db.scalars(
            select(models.Review)
            .options(joinedload(models.Review.user))
            .where(
                models.Review.vendor_id == vendor_id,
                models.Review.status == "approved",
            )
            .order_by(models.Review.created_at.desc())
        ).all()
    )
    avg, count = _avg_and_count(rows)
    return {"reviews": [_serialize(r) for r in rows], "avg_rating": avg, "count": count}


@router.post("/api/reviews/{review_id}/photos", response_model=schemas.ReviewOut)
def add_review_photo(
    review_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Attach a photo to a review. Only the review's own author may do this
    (401 when logged out, 403 otherwise). Max 3 photos per review."""
    review = db.get(models.Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only add photos to your own reviews")
    # Same disk-fill guard as dish photo uploads: 20/hour per IP.
    check_rate_limit(request, "review_photo_upload", limit=20, window_seconds=3600)
    photos = _review_photos(review)
    if len(photos) >= MAX_REVIEW_PHOTOS:
        raise HTTPException(
            status_code=400,
            detail=f"A review can have at most {MAX_REVIEW_PHOTOS} photos",
        )
    photos.append(save_uploaded_photo(file))
    review.photo_urls = json.dumps(photos)
    db.commit()
    db.refresh(review)
    review.user = db.get(models.User, review.user_id)
    return _serialize(review)


@router.patch("/api/reviews/{review_id}/reply", response_model=schemas.ReviewOut)
def reply_to_review(
    review_id: int,
    payload: schemas.ReviewReplyIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Vendor replies to a review on their own dish/shop.

    Empty/blank text clears the reply.
    """
    review = db.get(models.Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    if not any(v.id == review.vendor_id for v in user.vendors):
        raise HTTPException(status_code=403, detail="Not your review")
    text = (payload.text or "").strip()
    if text:
        review.vendor_reply = text
        review.replied_at = dt.datetime.utcnow()
    else:
        review.vendor_reply = None
        review.replied_at = None
    db.commit()
    db.refresh(review)
    review.user = db.get(models.User, review.user_id)
    return _serialize(review)
