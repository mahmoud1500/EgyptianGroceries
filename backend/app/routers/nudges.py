"""Reorder nudges (v29, Oct 2026).

GET /api/nudges (auth): dishes the logged-in account ordered in >= 2
distinct past orders whose most recent order is >= 21 days ago — candidates
for a "craving it again?" nudge.

POST /api/admin/nudges/send (admin only, in routers/admin.py): pushes the
nudge to every eligible user that has push tokens. Scheduled sending (cron /
APScheduler on the host) is documented in UPGRADE.md — the in-app manual
send works regardless.
"""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/nudges", tags=["nudges"])

NUDGE_MIN_ORDERS = 2  # ordered in at least this many distinct past orders
NUDGE_MIN_DAYS = 21  # most recent order at least this many days ago

# Push copy for reorder nudges: the Marketer's v29 deck, variants A–C.
# Variant selection (per the deck):
#   A (appetite-first)  — default, for recently-ordered dishes
#   B (time-skipper)     — for dishes ordered >= 7 days ago
#   C (warm vendor voice) — no selection criterion in the deck, kept for
#     manual/other use; never auto-selected.
# EN is the fallback; _nudge_copy() falls back to EN for unknown languages.
NUDGE_COPY = {
    "a": {
        "en": {
            "title": "Friday mahshi time? 🍲",
            "body": "{dish_name} from {vendor_name} is calling — reorder in one tap.",
        },
        "ar": {
            "title": "يوم الجمعة محشي؟ 🍲",
            "body": "{dish_name} من {vendor_name} بينادي عليك — اطلبه بضغطة واحدة.",
        },
    },
    "b": {
        "en": {
            "title": "It's been {days} days 😋",
            "body": "That {dish_name} from {vendor_name}… one tap brings it back.",
        },
        "ar": {
            "title": "فات {days} يوم 😋",
            "body": "الـ{dish_name} بتاع {vendor_name}… بضغطة واحدة يرجع تاني.",
        },
    },
    "c": {
        "en": {
            "title": "{vendor_name} has you covered 🥘",
            "body": "Craving {dish_name} again? Reorder in seconds.",
        },
        "ar": {
            "title": "{vendor_name} معاك 🥘",
            "body": "نفسك في الـ{dish_name} تاني؟ اطلبه في ثواني.",
        },
    },
}

# Deck criterion: variant B ("time-skipper") for dishes ordered >= 7 days ago.
# NOTE: current nudge eligibility already requires >= 21 days (NUDGE_MIN_DAYS),
# so variant B fires for every eligible nudge; A remains the <7-day fallback
# (reachable if eligibility is ever loosened).
NUDGE_VARIANT_B_MIN_DAYS = 7


def _nudge_copy(variant: str = "a", lang: str = "en") -> dict:
    variant_copy = NUDGE_COPY.get(variant) or NUDGE_COPY["a"]
    return variant_copy.get(lang) or variant_copy["en"]


def nudge_copy_for(nudge: dict, lang: str = "en") -> tuple[str, str]:
    """Render (title, body) for one nudge dict, picking the deck variant."""
    days = nudge.get("days_since_last") or 0
    variant = "b" if days >= NUDGE_VARIANT_B_MIN_DAYS else "a"
    copy = _nudge_copy(variant, lang)
    title = copy["title"].format(
        days=days,
        dish_name=nudge["dish_name"],
        vendor_name=nudge["vendor_name"],
    )
    body = copy["body"].format(
        days=days,
        dish_name=nudge["dish_name"],
        vendor_name=nudge["vendor_name"],
    )
    return title, body


def eligible_nudges(db: Session, user: models.User) -> list[dict]:
    """Nudge candidates for one user: dishes in >= 2 distinct non-cancelled
    past orders, most recent >= 21 days ago. Most-overdue first.

    Each dict matches schemas.NudgeOut. Bundle lines (dish_id NULL) never
    count — nudges are per dish.
    """
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)  # naive like created_at
    cutoff = now - dt.timedelta(days=NUDGE_MIN_DAYS)
    rows = db.execute(
        select(
            models.OrderItem.dish_id,
            func.count(distinct(models.Order.id)).label("n_orders"),
            func.max(models.Order.created_at).label("last_at"),
        )
        .join(models.Order, models.Order.id == models.OrderItem.order_id)
        .where(
            models.Order.customer_id == user.id,
            models.Order.status != "cancelled",
            models.OrderItem.dish_id.is_not(None),
        )
        .group_by(models.OrderItem.dish_id)
        .having(func.count(distinct(models.Order.id)) >= NUDGE_MIN_ORDERS)
    ).all()
    nudges: list[dict] = []
    for dish_id, _n_orders, last_at in rows:
        if last_at is None or last_at > cutoff:
            continue
        dish = db.get(models.Dish, dish_id)
        if dish is None:
            continue
        # Most recent order line for this dish by this user -> last price.
        last_line = db.scalar(
            select(models.OrderItem)
            .join(models.Order, models.Order.id == models.OrderItem.order_id)
            .where(
                models.Order.customer_id == user.id,
                models.Order.status != "cancelled",
                models.OrderItem.dish_id == dish_id,
            )
            .order_by(models.Order.created_at.desc())
            .limit(1)
        )
        vendor = dish.vendor
        nudges.append(
            {
                "dish_id": dish.id,
                "dish_name": dish.name,
                "vendor_id": dish.vendor_id,
                "vendor_name": vendor.name if vendor else "",
                "last_price": last_line.unit_price if last_line else dish.price,
                "photo_url": dish.photo_url or "",
                "days_since_last": (now.date() - last_at.date()).days,
            }
        )
    nudges.sort(key=lambda n: n["days_since_last"], reverse=True)
    return nudges


@router.get("", response_model=list[schemas.NudgeOut])
def list_nudges(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Reorder-nudge candidates for the logged-in account."""
    return eligible_nudges(db, user)
