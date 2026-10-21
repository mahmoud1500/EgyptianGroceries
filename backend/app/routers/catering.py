"""Public catering inquiries: anyone can ask about catering an event.

The admin works these from the /api/admin/catering inbox. Submissions are
rate-limited (10/hour per IP) and every admin is notified by email
(best effort — never breaks the request).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, emailer, models, schemas
from ..database import get_db
from ..ratelimit import check_rate_limit

router = APIRouter(prefix="/api/catering", tags=["catering"])


@router.post("", response_model=schemas.CateringOut, status_code=201)
def create_catering(
    payload: schemas.CateringIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Submit a catering inquiry. Public — no account needed."""
    check_rate_limit(request, "catering_create", limit=10, window_seconds=3600)
    r = models.CateringRequest(
        event_type=payload.event_type,
        event_date=payload.event_date,
        location=payload.location,
        contact_name=payload.contact_name,
        phone=payload.phone,
        email=str(payload.email) if payload.email else None,
        food_type=payload.food_type,
        guest_count=payload.guest_count,
        notes=(payload.notes or "").strip() or None,
        status="new",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    # Notify every admin (best effort — never breaks the request).
    try:
        admins = list(db.scalars(select(models.User).where(models.User.role == "admin")))
        for a in admins:
            emailer.send_catering_notification(a.email, r)
    except Exception as exc:  # noqa: BLE001
        print(f"[catering] admin notify failed: {exc}")
    return schemas.CateringOut.model_validate(r)
