"""New-dish announcements ("New from your cooks").

GET /api/announcements (auth): announcements from vendors the customer has
ordered from, newest first, limit 20. Each row carries `unseen` =
created_at > the customer's last_announcement_seen_at (NULL = never viewed
→ everything is unseen).
POST /api/announcements/seen (auth): marks the announcements list as viewed
(sets last_announcement_seen_at = now).
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


@router.get("", response_model=list[schemas.AnnouncementOut])
def list_announcements(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Announcements from vendors this customer has ordered from."""
    vendor_ids = list(
        db.scalars(
            select(models.Order.vendor_id)
            .where(models.Order.customer_id == user.id)
            .distinct()
        ).all()
    )
    if not vendor_ids:
        return []
    rows = (
        db.scalars(
            select(models.DishAnnouncement)
            .options(
                joinedload(models.DishAnnouncement.dish),
                joinedload(models.DishAnnouncement.vendor),
            )
            .where(models.DishAnnouncement.vendor_id.in_(vendor_ids))
            .order_by(models.DishAnnouncement.created_at.desc())
            .limit(20)
        )
        .unique()
        .all()
    )
    seen_at = user.last_announcement_seen_at
    out = []
    for ann in rows:
        dish = ann.dish
        vendor = ann.vendor
        out.append(
            schemas.AnnouncementOut(
                dish_id=ann.dish_id,
                dish_name=dish.name if dish else "",
                # v52: current Arabic name from the dish.
                dish_name_ar=dish.name_ar if dish else None,
                vendor_name=vendor.name if vendor else "",
                created_at=ann.created_at,
                unseen=(seen_at is None) or (ann.created_at > seen_at),
                kind="dish",
            )
        )
    # === v40: admin broadcasts in the same feed. Audience "all" reaches
    # every customer; audience "vendor" reaches customers who ordered from
    # that vendor. Merged with dish announcements, newest first.
    try:
        b_rows = (
            db.scalars(
                select(models.Broadcast)
                .order_by(models.Broadcast.created_at.desc())
                .limit(20)
            ).all()
        )
        for b in b_rows:
            visible = b.audience == "all" or (
                b.audience == "vendor"
                and b.vendor_id is not None
                and b.vendor_id in vendor_ids
            )
            if not visible:
                continue
            vname = ""
            if b.vendor_id:
                v = db.get(models.Vendor, b.vendor_id)
                vname = v.name if v else ""
            out.append(
                schemas.AnnouncementOut(
                    dish_id=0,
                    dish_name="",
                    vendor_name=vname,
                    created_at=b.created_at,
                    unseen=(seen_at is None) or (b.created_at > seen_at),
                    kind="broadcast",
                    broadcast_id=b.id,
                    title_en=b.title_en,
                    title_ar=b.title_ar,
                    body_en=b.body_en,
                    body_ar=b.body_ar,
                )
            )
        out.sort(key=lambda a: a.created_at, reverse=True)
        out = out[:20]
    except Exception as exc:  # noqa: BLE001 — feed must never break on broadcasts
        print(f"[announcements] broadcast merge failed: {exc}")
    return out


@router.post("/seen")
def mark_announcements_seen(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Mark the announcements feed as viewed right now."""
    user.last_announcement_seen_at = dt.datetime.now()
    db.commit()
    return {"ok": True}
