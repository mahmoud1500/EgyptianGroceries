"""Support tickets: customers/vendors file complaints, the site admin answers them."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, emailer, models, notifier, schemas
from ..database import get_db
from ..ratelimit import check_rate_limit

router = APIRouter(prefix="/api/complaints", tags=["complaints"])


def _out(c: models.Complaint, db: Session) -> schemas.ComplaintOut:
    reporter = db.get(models.User, c.reporter_id)
    vendor_name = None
    if c.vendor_id:
        v = db.get(models.Vendor, c.vendor_id)
        vendor_name = v.name if v else None
    return schemas.ComplaintOut(
        id=c.id,
        reporter_id=c.reporter_id,
        reporter_name=reporter.name if reporter else None,
        reporter_email=reporter.email if reporter else None,
        reporter_role=reporter.role if reporter else None,
        category=c.category,
        subject=c.subject,
        message=c.message,
        order_id=c.order_id,
        vendor_id=c.vendor_id,
        vendor_name=vendor_name,
        status=c.status,
        admin_reply=c.admin_reply or None,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _check_links(payload: schemas.ComplaintIn, db: Session, user: models.User) -> None:
    """An order link must exist and belong to the reporter (or their shop)."""
    if payload.order_id:
        o = db.get(models.Order, payload.order_id)
        if o is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if user.role == "customer" and o.customer_id != user.id:
            raise HTTPException(status_code=403, detail="Not your order")
        if user.role == "vendor" and o.vendor.owner_id != user.id:
            raise HTTPException(status_code=403, detail="Not your shop's order")
    if payload.vendor_id and db.get(models.Vendor, payload.vendor_id) is None:
        raise HTTPException(status_code=404, detail="Vendor not found")


@router.post("", response_model=schemas.ComplaintOut)
def create_complaint(
    payload: schemas.ComplaintIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    check_rate_limit(request, "complaint_create", limit=30, window_seconds=3600)
    _check_links(payload, db, user)
    c = models.Complaint(
        reporter_id=user.id,
        category=payload.category,
        subject=payload.subject.strip(),
        message=payload.message.strip(),
        order_id=payload.order_id,
        vendor_id=payload.vendor_id,
        status="open",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    # Notify every admin (best effort — never breaks the request).
    try:
        admins = list(db.scalars(select(models.User).where(models.User.role == "admin")))
        for a in admins:
            emailer.send_complaint_notification(a.email, user, c)
    except Exception as exc:  # noqa: BLE001
        print(f"[complaints] admin notify failed: {exc}")
    # === v40: admin alert push + SMS (toggleable). Never breaks the request. ===
    try:
        notifier.alert_admins(
            db, "ticket",
            f"New support ticket — {c.subject}",
            f"New support ticket: {c.subject}\nتذكرة دعم جديدة: {c.subject}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[complaints] admin alert failed: {exc}")
    return _out(c, db)


@router.get("/mine", response_model=list[schemas.ComplaintOut])
def my_complaints(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    rows = list(
        db.scalars(
            select(models.Complaint)
            .where(models.Complaint.reporter_id == user.id)
            .order_by(models.Complaint.created_at.desc())
        )
    )
    return [_out(c, db) for c in rows]


@router.get("", response_model=list[schemas.ComplaintOut])
def all_complaints(
    status: str | None = Query(default=None, max_length=20),
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.require_staff),
):
    q = select(models.Complaint).order_by(models.Complaint.created_at.desc())
    if status:
        q = q.where(models.Complaint.status == status.strip().lower())
    return [_out(c, db) for c in db.scalars(q)]


@router.patch("/{complaint_id}", response_model=schemas.ComplaintOut)
def reply_complaint(
    complaint_id: int,
    payload: schemas.ComplaintReply,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.require_staff),
):
    c = db.get(models.Complaint, complaint_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    c.admin_reply = payload.admin_reply.strip()
    c.status = payload.status
    db.commit()
    db.refresh(c)
    # Notify the reporter (best effort).
    try:
        reporter = db.get(models.User, c.reporter_id)
        if reporter:
            emailer.send_complaint_reply(reporter.email, reporter, c)
    except Exception as exc:  # noqa: BLE001
        print(f"[complaints] reporter notify failed: {exc}")
    return _out(c, db)
