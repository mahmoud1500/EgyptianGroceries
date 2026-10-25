"""Admin-only hybrid delivery dispatch and delivery-cost ledger endpoints.

Dispatch is manual in this first version. No courier API is called and no
courier is paid automatically.
"""
import datetime as dt
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, models
from ..database import get_db

router = APIRouter(prefix="/api/delivery", tags=["delivery"])
Money = Decimal


class DeliveryJobCreate(BaseModel):
    mode: Literal["vendor", "third_party"] = "third_party"
    provider: str = Field(default="manual", min_length=1, max_length=40)
    provider_reference: str | None = Field(default=None, max_length=120)
    quoted_cost: Money = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2)
    customer_fee: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)


class DeliveryJobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["vendor", "third_party"] | None = None
    provider: str | None = Field(default=None, min_length=1, max_length=40)
    provider_reference: str | None = Field(default=None, max_length=120)
    status: Literal["pending", "assigned", "picked_up", "delivered", "failed", "cancelled"] | None = None
    quoted_cost: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    actual_cost: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    customer_fee: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    payment_status: Literal["unpaid", "paid", "waived"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


def _serialize(job: models.DeliveryJob) -> dict:
    return {
        "id": job.id,
        "order_id": job.order_id,
        "mode": job.mode,
        "provider": job.provider,
        "provider_reference": job.provider_reference,
        "status": job.status,
        "quoted_cost": str(job.quoted_cost),
        "actual_cost": str(job.actual_cost) if job.actual_cost_confirmed else None,
        "actual_cost_confirmed": bool(job.actual_cost_confirmed),
        "customer_fee": str(job.customer_fee),
        "platform_subsidy": str(job.platform_subsidy) if job.actual_cost_confirmed else None,
        "payment_status": job.payment_status,
        "notes": job.notes,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _recalculate_subsidy(job: models.DeliveryJob) -> None:
    if not job.actual_cost_confirmed:
        # Unknown is not equivalent to zero; the serializer emits null.
        job.platform_subsidy = Decimal("0.00")
        return
    actual = Decimal(str(job.actual_cost or 0))
    customer_fee = Decimal(str(job.customer_fee or 0))
    job.platform_subsidy = max(Decimal("0.00"), actual - customer_fee).quantize(Decimal("0.01"))


def _record_event(db: Session, order_id: int, message: str, meta: dict) -> None:
    import json
    db.add(models.OrderEvent(
        order_id=order_id,
        event_type="delivery",
        message=message,
        meta=json.dumps(meta, default=str),
    ))


@router.get("/jobs")
def list_delivery_jobs(
    status: str | None = None,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.require_admin),
):
    query = select(models.DeliveryJob).order_by(models.DeliveryJob.created_at.desc())
    if status:
        allowed = {"pending", "assigned", "picked_up", "delivered", "failed", "cancelled"}
        if status not in allowed:
            raise HTTPException(status_code=400, detail="Invalid delivery status")
        query = query.where(models.DeliveryJob.status == status)
    return [_serialize(job) for job in db.scalars(query).all()]


@router.post("/orders/{order_id}/job", status_code=201)
def create_delivery_job(
    order_id: int,
    payload: DeliveryJobCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.require_admin),
):
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.fulfillment != "delivery":
        raise HTTPException(status_code=400, detail="Delivery jobs require a delivery order")
    existing = db.scalar(select(models.DeliveryJob).where(models.DeliveryJob.order_id == order_id))
    if existing:
        raise HTTPException(status_code=409, detail="A delivery job already exists for this order")
    customer_fee = payload.customer_fee
    if customer_fee is None:
        customer_fee = Decimal(str(order.delivery_fee or 0))
    job = models.DeliveryJob(
        order_id=order.id,
        mode=payload.mode,
        provider="vendor" if payload.mode == "vendor" and payload.provider == "manual" else payload.provider,
        provider_reference=payload.provider_reference,
        status="pending",
        quoted_cost=payload.quoted_cost,
        actual_cost=Decimal("0.00"),
        actual_cost_confirmed=False,
        customer_fee=customer_fee,
        platform_subsidy=Decimal("0.00"),
        payment_status="unpaid",
        notes=payload.notes,
    )
    db.add(job)
    db.flush()
    _record_event(db, order.id, "Delivery job created", {
        "delivery_job_id": job.id, "mode": job.mode, "provider": job.provider,
        "customer_fee": str(customer_fee), "quoted_cost": str(payload.quoted_cost),
    })
    db.commit()
    db.refresh(job)
    return _serialize(job)


@router.patch("/jobs/{job_id}")
def update_delivery_job(
    job_id: int,
    payload: DeliveryJobUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(auth.require_admin),
):
    job = db.get(models.DeliveryJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Delivery job not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return _serialize(job)
    old_status = job.status
    transitions = {
        "pending": {"pending", "assigned", "cancelled", "failed"},
        "assigned": {"assigned", "picked_up", "cancelled", "failed"},
        "picked_up": {"picked_up", "delivered", "failed"},
        "delivered": {"delivered"},
        "failed": {"failed", "pending", "cancelled"},
        "cancelled": {"cancelled", "pending"},
    }
    new_status = changes.get("status", old_status)
    if new_status not in transitions.get(old_status, set()):
        raise HTTPException(status_code=409, detail=f"Invalid delivery status transition: {old_status} -> {new_status}")

    # Explicitly setting actual_cost (including 0.00) is the evidence that
    # the amount was reviewed. An explicit null clears that confirmation.
    if "actual_cost" in changes:
        job.actual_cost_confirmed = changes["actual_cost"] is not None
        if changes["actual_cost"] is None:
            changes["actual_cost"] = Decimal("0.00")

    if new_status == "delivered" and not job.actual_cost_confirmed:
        raise HTTPException(status_code=409, detail="Record the actual delivery cost before marking the job delivered")
    if changes.get("payment_status") == "paid":
        if new_status != "delivered" or not job.actual_cost_confirmed:
            raise HTTPException(status_code=409, detail="A delivery cost can only be marked paid after delivery and cost confirmation")

    order = db.get(models.Order, job.order_id) if new_status == "delivered" else None
    if order is not None and order.status == "cancelled":
        raise HTTPException(status_code=409, detail="A cancelled order cannot be marked delivered")

    for key, value in changes.items():
        setattr(job, key, value)
    _recalculate_subsidy(job)
    if new_status == "delivered" and order is not None and order.status != "completed":
        previous_order_status = order.status
        order.status = "completed"
        _record_event(db, order.id, "Order completed by delivery confirmation", {
            "delivery_job_id": job.id,
            "status_before": previous_order_status,
            "status_after": order.status,
        })
    _record_event(db, job.order_id, "Delivery job updated", {
        "delivery_job_id": job.id, "changes": changes,
        "status_before": old_status, "status_after": job.status,
        "actual_cost": str(job.actual_cost), "customer_fee": str(job.customer_fee),
        "platform_subsidy": str(job.platform_subsidy),
    })
    db.commit()
    db.refresh(job)
    return _serialize(job)
