"""Vendor applications: the public "become a vendor" form.

The admin triages applications at /api/admin/applications. Approving an
application creates a paused Vendor record; creating the login and unpausing
stay manual (documented in the admin route).

WA permit gate (Oct 2026): every applicant must hold a WA Food Worker Card
and at least one operating permit (Food Establishment Permit for hot/prepared
meals, or a Cottage Food Permit for cottage foods only), and must attest
their permits are current and valid. Every claimed permit needs its number,
and any provided expiry date must not be in the past (America/Los_Angeles)
nor more than 10 years out. Enforced server-side — the frontend checks
mirror this but are never trusted alone.
"""
import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models, notifier, schemas
from ..database import get_db
from ..ratelimit import check_rate_limit

router = APIRouter(tags=["applications"])


def _check_permit(label: str, claimed: bool, number: str | None, expiry: dt.date | None,
                  today: dt.date, max_expiry: dt.date) -> None:
    """Number-required + expiry sanity for one claimed permit. Raises 400."""
    if not claimed:
        return
    if not (number or "").strip():
        raise HTTPException(
            status_code=400,
            detail=f"A permit number is required for the {label}.",
        )
    if expiry is not None:
        if expiry < today:
            raise HTTPException(
                status_code=400,
                detail=f"The {label} expired on {expiry.isoformat()} — permits must be current and valid.",
            )
        if expiry > max_expiry:
            raise HTTPException(
                status_code=400,
                detail=f"The {label} expiry date is too far in the future — please check the date.",
            )


@router.post("/api/applications", response_model=schemas.VendorApplicationOut, status_code=201)
def submit_application(
    payload: schemas.VendorApplicationIn,
    request: Request,
    db: Session = Depends(get_db),
):
    check_rate_limit(request, "vendor_application", limit=10, window_seconds=3600)
    # WA permit gate — 400s, checked in a fixed order so the applicant gets
    # the most actionable error first.
    if not payload.permits_attested:
        raise HTTPException(
            status_code=400,
            detail="Please confirm your permits are current and valid (attestation required).",
        )
    if not payload.permits_food_worker_card:
        raise HTTPException(
            status_code=400,
            detail="A WA Food Worker Card is required to apply as a vendor.",
        )
    if not (payload.permits_establishment or payload.permits_cottage):
        raise HTTPException(
            status_code=400,
            detail="An operating permit is required: a Food Establishment Permit "
            "(county health district) for hot/prepared meals, or a Cottage Food "
            "Permit (WSDA) for cottage foods only.",
        )
    # P1/P2: every claimed permit needs its number; provided expiries must be
    # current (LA date) and within a 10-year sanity cap. No expiry given →
    # attestation remains the control.
    la_today = dt.datetime.now(ZoneInfo("America/Los_Angeles")).date()
    max_expiry = la_today + dt.timedelta(days=365 * 10)
    _check_permit("WA Food Worker Card", payload.permits_food_worker_card,
                  payload.permits_food_worker_card_number, payload.permits_food_worker_card_expiry,
                  la_today, max_expiry)
    _check_permit("Food Establishment Permit", payload.permits_establishment,
                  payload.permits_establishment_number, payload.permits_establishment_expiry,
                  la_today, max_expiry)
    _check_permit("Cottage Food Permit", payload.permits_cottage,
                  payload.permits_cottage_number, payload.permits_cottage_expiry,
                  la_today, max_expiry)
    if payload.permits_business_license and not (payload.permits_business_license_ubi or "").strip():
        raise HTTPException(
            status_code=400,
            detail="A UBI number is required for the WA Business License.",
        )
    app = models.VendorApplication(
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
        city=payload.city,
        cooking=payload.cooking,
        message=(payload.message or "").strip() or None,
        status="new",
        permits_food_worker_card=payload.permits_food_worker_card,
        permits_food_worker_card_number=(payload.permits_food_worker_card_number or "").strip() or None,
        permits_food_worker_card_expiry=payload.permits_food_worker_card_expiry,
        permits_establishment=payload.permits_establishment,
        permits_establishment_number=(payload.permits_establishment_number or "").strip() or None,
        permits_establishment_expiry=payload.permits_establishment_expiry,
        permits_cottage=payload.permits_cottage,
        permits_cottage_number=(payload.permits_cottage_number or "").strip() or None,
        permits_cottage_expiry=payload.permits_cottage_expiry,
        permits_business_license=payload.permits_business_license,
        permits_business_license_ubi=(payload.permits_business_license_ubi or "").strip() or None,
        permits_attested=payload.permits_attested,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    # === v40: admin alert (push + SMS, toggleable). Never breaks the request. ===
    try:
        notifier.alert_admins(
            db, "application",
            f"New vendor application — {app.business_name or app.contact_name}",
            f"New vendor application: {app.business_name or app.contact_name}\nطلب انضمام بائع جديد: {app.business_name or app.contact_name}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[applications] admin alert failed: {exc}")
    return app
