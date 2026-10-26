"""Order routes: customers place orders; vendors advance status."""
import datetime as dt  # === FEATURE 10: payment-failure timestamps ===
import json
import uuid
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from .. import auth, emailer, flash_sales, loyalty, models, notifier, referrals, schemas
from ..commission import commission_for_amount, commissionable_food_amount, is_direct_payment_method
from ..database import get_db
from ..photo_uploads import delete_uploaded_file, save_uploaded_photo
from ..ratelimit import check_rate_limit
from ..order_windows import dish_order_window, order_window_block_message
from .pickup_slots import slot_label_with_date, slot_next_date  # === FEATURE 8 ===
from .promos import validate_promo
from .bundles import _bundle_ended  # === v29: holiday-feast ended check ===
from .stripe import _stripe_client
from .vendors import vendor_open_status

router = APIRouter(prefix="/api/orders", tags=["orders"])

# new -> preparing -> ready -> on_the_way -> completed ; cancelled allowed before completed.
# on_the_way is delivery-only (pickup orders go ready -> completed).
# Vendors move forward only (jumps allowed, e.g. new -> completed), never backwards.
_ORDER_FLOW = ["new", "preparing", "ready", "on_the_way", "completed"]
_NEXT = {"new": "preparing", "preparing": "ready", "ready": "completed"}
_MARKET_TZ = ZoneInfo("America/Los_Angeles")


def _validate_pickup_time(
    vendor: models.Vendor,
    pickup_at: dt.datetime,
    *,
    active_slots: list[models.PickupSlot],
    pickup_slot_id: int | None,
    now: dt.datetime | None = None,
) -> tuple[dt.datetime, models.PickupSlot | None]:
    """Validate a pickup appointment in marketplace time and store it as UTC-naive."""
    market_time = (
        pickup_at.replace(tzinfo=_MARKET_TZ)
        if pickup_at.tzinfo is None
        else pickup_at.astimezone(_MARKET_TZ)
    )
    now = now or dt.datetime.now(_MARKET_TZ)
    now = now.replace(tzinfo=_MARKET_TZ) if now.tzinfo is None else now.astimezone(_MARKET_TZ)
    if market_time <= now:
        raise HTTPException(status_code=400, detail="Pickup time must be in the future")
    prep_minutes = max(0, int(vendor.prep_minutes or 0))
    if market_time < now + dt.timedelta(minutes=prep_minutes):
        raise HTTPException(
            status_code=400,
            detail=f"Pickup time must allow at least {prep_minutes} minutes for preparation",
        )

    weekday_sunday_first = (market_time.weekday() + 1) % 7
    closed_days = {
        int(day.strip())
        for day in (vendor.closed_weekdays or "").split(",")
        if day.strip().isdigit() and 0 <= int(day.strip()) <= 6
    }
    if weekday_sunday_first in closed_days:
        raise HTTPException(status_code=400, detail="The vendor is closed on the selected pickup day")

    if vendor.open_time or vendor.close_time or not active_slots:
        open_time = dt.time.fromisoformat(vendor.open_time or "10:00")
        close_time = dt.time.fromisoformat(vendor.close_time or "20:00")
        selected = market_time.time().replace(tzinfo=None)
        if open_time < close_time:
            in_hours = open_time <= selected < close_time
        elif open_time > close_time:
            in_hours = selected >= open_time or selected < close_time
        else:
            in_hours = True
        if not in_hours:
            raise HTTPException(status_code=400, detail="Pickup time is outside the vendor's opening hours")

    selected_slot = None
    if active_slots:
        selected_slot = next((slot for slot in active_slots if slot.id == pickup_slot_id), None)
        if selected_slot is None:
            raise HTTPException(status_code=400, detail="Please choose a valid pickup slot")
        next_date = slot_next_date(selected_slot, today=now.date(), now=now)
        if market_time.date() != next_date or market_time.strftime("%H:%M") != selected_slot.start_time:
            raise HTTPException(
                status_code=400,
                detail="Pickup time must match the next available time for the selected slot",
            )
    elif pickup_slot_id is not None:
        raise HTTPException(status_code=400, detail="This vendor does not offer pickup slots")

    utc_naive = market_time.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return utc_naive, selected_slot


def _transition_error(order: models.Order, target: str) -> str | None:
    """Error message if the vendor may NOT move `order` to `target`; None if OK."""
    previous = order.status
    if previous == "cancelled":
        return "Cancelled orders cannot be changed"
    if target == "cancelled":
        if previous == "completed":
            return "Completed orders cannot be cancelled"
        return None
    if target == previous:
        return f"Order is already '{target}'"
    if target == "on_the_way":
        if order.fulfillment != "delivery":
            return "The 'on the way' status is only for delivery orders"
        if previous != "ready":
            return "An order can only be marked on the way once it is ready"
        return None
    if previous == "on_the_way":
        if target == "completed":
            return None
        return f"Cannot move order from 'on_the_way' to '{target}'"
    if _ORDER_FLOW.index(target) < _ORDER_FLOW.index(previous):
        return f"Cannot move order backwards from '{previous}' to '{target}'"
    return None

# Sales tax rate applied to the order subtotal (not the delivery fee).
# Currently 0 — no tax is charged. Set to the local rate (e.g. Decimal("0.101")
# for ~10.1%) to start collecting it; the customer breakdown, order records,
# and confirmation emails all read this one constant.
# Frontend mirror: TAX_RATE in frontend/app.js (must be kept in sync).
TAX_RATE = Decimal("0.00")


def _commission_rate_for_order(db: Session, order: models.Order) -> Decimal:
    """Resolve the effective vendor/global commission rate for a checkout order."""
    vendor = db.get(models.Vendor, order.vendor_id)
    if vendor is not None and vendor.commission_rate is not None:
        return Decimal(str(vendor.commission_rate))
    row = db.scalar(select(models.Setting).where(models.Setting.key == "commission_percent"))
    try:
        return Decimal(str(row.value)) if row is not None else Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _current_tax_rate(db: Session) -> Decimal:
    """Sales tax rate: the admin-set `tax_rate` site setting when present,
    else the TAX_RATE fallback (0.00). Invalid stored values fall back too —
    a bad setting must never break checkout."""
    try:
        row = db.scalar(select(models.Setting).where(models.Setting.key == "tax_rate"))
        if row is not None and (row.value or "").strip() != "":
            rate = Decimal(row.value)
            if Decimal("0") <= rate <= Decimal("1"):
                return rate
    except Exception:  # noqa: BLE001 — fall back to the constant
        pass
    return TAX_RATE


def _record_stock_movement(
    db: Session,
    dish: models.Dish,
    delta: int,
    reason: str,
    order_id: int | None = None,
) -> None:
    """Append one StockMovement row. Callers flush/commit; this only adds."""
    db.add(
        models.StockMovement(
            dish_id=dish.id,
            delta=delta,
            reason=reason,
            order_id=order_id,
            stock_after=dish.stock_quantity,
        )
    )


def _restore_stock_on_cancel(db: Session, order: models.Order) -> None:
    """Restore ordered quantities to each dish's stock on cancellation
    (reason 'cancel_restore'). Idempotency comes from the state machine:
    cancelling an already-cancelled order is rejected everywhere, so this
    runs exactly once per cancellation. Dishes with NULL (untracked) stock
    are skipped — nothing to restore."""
    restored_any = False
    for item in order.items:
        dish = db.get(models.Dish, item.dish_id)
        if dish is None or dish.stock_quantity is None:
            continue
        # Atomic increment (same lost-update class as DBA P0-2): two
        # concurrent cancels of different orders for the same dish must
        # not lose a restore. The movement's stock_after reads the
        # post-update value via the expire below.
        result = db.execute(
            update(models.Dish)
            .where(models.Dish.id == dish.id)
            .values(stock_quantity=models.Dish.stock_quantity + item.quantity)
        )
        if result.rowcount != 1:
            continue  # dish vanished mid-cancel; nothing to restore
        db.expire(dish, ["stock_quantity"])
        _record_stock_movement(db, dish, item.quantity, "cancel_restore", order.id)
        restored_any = True
    if restored_any:
        _log_event(
            db, order, "stock",
            "Stock restored for cancelled order",
            {"restored": True},
        )


def _log_event(db: Session, order: models.Order, event_type: str,
               message: str, meta: dict | None = None) -> models.OrderEvent:
    ev = models.OrderEvent(
        order_id=order.id,
        event_type=event_type,
        message=message,
        meta=json.dumps(meta or {}),
    )
    db.add(ev)
    return ev


def _stripe_payment_intent_id(db: Session, order: models.Order, stripe) -> str | None:
    """Resolve a PaymentIntent from either Checkout Session or wallet payment metadata."""
    events = db.scalars(
        select(models.OrderEvent)
        .where(
            models.OrderEvent.order_id == order.id,
            models.OrderEvent.event_type == "payment",
        )
        .order_by(models.OrderEvent.created_at.desc(), models.OrderEvent.id.desc())
    )
    for ev in events:
        try:
            meta = json.loads(ev.meta) if ev.meta else {}
        except (ValueError, TypeError):
            continue
        if not isinstance(meta, dict):
            continue
        pi_id = meta.get("payment_intent")
        if isinstance(pi_id, str) and pi_id.startswith("pi_"):
            return pi_id
        session_id = meta.get("stripe_session")
        if isinstance(session_id, str) and session_id.startswith("cs_"):
            session = stripe.checkout.Session.retrieve(session_id)
            pi = session.get("payment_intent") if hasattr(session, "get") else None
            resolved = pi.get("id") if hasattr(pi, "get") else pi
            if isinstance(resolved, str) and resolved.startswith("pi_"):
                return resolved
    return None


def _unmatched_stripe_refunds(db: Session, stripe, payment_intent_id: str) -> list[str]:
    """Return Stripe refund IDs missing from local refund events for this PaymentIntent.

    Dashboard/API refunds are visible to Stripe but may not exist in order_events.
    A missing local record makes per-vendor attribution unsafe, so callers must
    stop automatic refunds and require reconciliation instead of guessing.
    """
    listed = stripe.Refund.list(payment_intent=payment_intent_id, limit=100)
    refunds = listed.get("data", []) if hasattr(listed, "get") else getattr(listed, "data", [])
    has_more = listed.get("has_more", False) if hasattr(listed, "get") else getattr(listed, "has_more", False)
    if has_more:
        raise RuntimeError("Stripe refund list is paginated; complete reconciliation is required")

    known_ids: set[str] = set()
    events = db.scalars(
        select(models.OrderEvent).where(models.OrderEvent.event_type == "refund")
    )
    for event in events:
        try:
            meta = json.loads(event.meta) if event.meta else {}
        except (ValueError, TypeError):
            continue
        if isinstance(meta, dict) and isinstance(meta.get("refund_id"), str):
            known_ids.add(meta["refund_id"])

    unmatched: list[str] = []
    for refund in refunds or []:
        refund_id = refund.get("id") if hasattr(refund, "get") else getattr(refund, "id", None)
        status = refund.get("status") if hasattr(refund, "get") else getattr(refund, "status", None)
        # A failed refund did not move money. Every non-terminal/unknown
        # status blocks a new refund, even when its ID is already logged.
        if status in (None, "pending", "requires_action"):
            raise RuntimeError(
                f"Stripe refund {refund_id or '<unknown>'} has unresolved status {status!r}"
            )
        if status not in ("succeeded", "failed"):
            raise RuntimeError(
                f"Stripe refund {refund_id or '<unknown>'} has unrecognized status {status!r}"
            )
        if status == "succeeded" and (
            not isinstance(refund_id, str) or refund_id not in known_ids
        ):
            unmatched.append(refund_id if isinstance(refund_id, str) else "<missing-refund-id>")
    return unmatched


def _stripe_refund_on_cancel(db: Session, order: models.Order) -> None:
    """Refund only this vendor sub-order's outstanding amount; never block cancellation."""
    if not order.paid or order.payment_method != "credit_card":
        _log_event(
            db, order, "refund", "No refund issued — order was not paid by card",
            {"paid": order.paid, "payment_method": order.payment_method},
        )
        return

    stripe = _stripe_client()
    if stripe is None:
        _log_event(db, order, "refund", "No refund issued — Stripe not configured", {})
        return

    try:
        pi_id = _stripe_payment_intent_id(db, order, stripe)
    except Exception as exc:  # Stripe lookup failure; cancellation still proceeds.
        print(f"[orders] Stripe PaymentIntent lookup failed: {exc}")
        _log_event(db, order, "refund", "Stripe refund FAILED — payment lookup failed; settle manually",
                   {"error": str(exc)[:200]})
        return
    if not pi_id:
        _log_event(
            db, order, "refund",
            "No refund issued — no Stripe PaymentIntent reference found; settle manually",
            {"paid": True},
        )
        return

    # Reconcile Stripe's source of truth before issuing another refund. A refund
    # created in the Stripe Dashboard (or another integration) may not be in
    # this order's event log. If any refund for this PaymentIntent is unknown,
    # stop here: a multi-vendor checkout must never guess which sub-order owns it.
    try:
        unmatched_refunds = _unmatched_stripe_refunds(db, stripe, pi_id)
    except Exception as exc:  # Fail closed when reconciliation cannot be completed.
        _log_event(
            db, order, "refund",
            "Stripe refund NOT issued — refund reconciliation unavailable; settle manually",
            {"payment_intent": pi_id, "reconciliation_error": str(exc)[:200]},
        )
        return
    if unmatched_refunds:
        _log_event(
            db, order, "refund",
            "Stripe refund NOT issued — unmatched Stripe refund(s) require manual reconciliation",
            {"payment_intent": pi_id, "unmatched_refund_ids": unmatched_refunds},
        )
        return

    already_refunded = _successful_refund_total(db, order.id)
    order_total = Decimal(str(order.total or 0))
    remaining = max(Decimal("0"), order_total - already_refunded)
    amount_cents = int((remaining * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_DOWN))
    if amount_cents <= 0:
        _log_event(
            db, order, "refund", "No refund issued — order already fully refunded",
            {"already_refunded": str(already_refunded)},
        )
        return

    # Stable per-order amount key prevents duplicate refunds if the request is retried.
    try:
        refund = stripe.Refund.create(
            payment_intent=pi_id,
            amount=amount_cents,
            idempotency_key=f"order-cancel-refund-{order.id}-{amount_cents}",
        )
    except Exception as exc:  # Stripe rejected/failed the request.
        print(f"[orders] Stripe refund failed: {exc}")
        _log_event(
            db, order, "refund", "Stripe refund FAILED — settle manually",
            {"error": str(exc)[:200], "amount": str(remaining), "payment_intent": pi_id},
        )
        return

    # Stripe has accepted the refund. Record its actual ID/amount separately so
    # a database logging issue is not misrepresented as a Stripe API failure.
    refund_id = refund.get("id") if hasattr(refund, "get") else getattr(refund, "id", None)
    status = refund.get("status") if hasattr(refund, "get") else getattr(refund, "status", None)
    actual_cents = refund.get("amount", amount_cents) if hasattr(refund, "get") else amount_cents
    actual_amount = (Decimal(str(actual_cents)) / Decimal("100")).quantize(Decimal("0.01"))
    if status != "succeeded":
        # Stripe accepted the request but has not confirmed the money moved.
        # Log it for reconciliation, but never count it as refunded.
        _log_event(
            db, order, "refund",
            f"Stripe refund NOT confirmed (status={status or 'unknown'}); reconcile manually",
            {"refund_id": refund_id, "amount": str(actual_amount),
             "payment_intent": pi_id, "stripe_status": status or "unknown"},
        )
        return
    try:
        _log_event(
            db, order, "refund",
            f"Stripe refund issued: {refund_id} for ${actual_amount:.2f}",
            {"refund_id": refund_id, "amount": str(actual_amount),
             "payment_intent": pi_id, "stripe_status": status},
        )
        order.refunded_amount = Decimal(str(order.refunded_amount or 0)) + actual_amount
    except Exception as exc:  # Reconciliation required; do not claim Stripe failed.
        # Do not roll back here: this helper runs inside the cancellation
        # transaction, and a rollback would undo the cancellation as well.
        print(
            f"[orders] RECONCILIATION REQUIRED: Stripe refund {refund_id} "
            f"succeeded for {actual_amount}, but local logging failed: {exc}"
        )


def _successful_refund_total(db: Session, order_id: int) -> Decimal:
    """Sum of SUCCESSFUL refund amounts from an order's event log.

    Excludes FAILED attempts (meta has "error", or message contains
    "FAILED") and notes without an amount — the same rule as the admin
    refund guard. Used by the refund idempotency check and the v40
    refunded_amount backfill. Never raises.
    """
    total = Decimal("0")
    try:
        events = db.scalars(
            select(models.OrderEvent).where(
                models.OrderEvent.order_id == order_id,
                models.OrderEvent.event_type == "refund",
            )
        )
    except Exception:  # noqa: BLE001 — backfill path on very old DBs
        return total
    for ev in events:
        if "FAILED" in (ev.message or ""):
            continue
        try:
            meta = json.loads(ev.meta) if ev.meta else {}
        except (ValueError, TypeError):
            continue
        if not isinstance(meta, dict) or "error" in meta:
            continue
        # New events record Stripe's actual status. Only succeeded refunds
        # count; legacy events without this field retain the old behavior.
        if "stripe_status" in meta and meta.get("stripe_status") != "succeeded":
            continue
        if meta.get("amount") is None:
            continue
        try:
            total += Decimal(str(meta["amount"]))
        except (InvalidOperation, ValueError):
            continue
    return total


def _completion_email(order: models.Order) -> tuple[str, str]:
    """Build the 'order completed' customer email.

    NOTE: the demo build only records/logs the email — nothing is really sent.
    Wire this to a real mail service (e.g. SendGrid, SES) for production.
    """
    vendor_name = order.vendor.name if order.vendor else "your vendor"
    customer_name = order.customer.name if order.customer else "there"
    subject = f"Your order #{order.id} from {vendor_name} is complete! ✅"
    lines = [
        f"Hi {customer_name},",
        "",
        f"Great news — your order #{order.id} from {vendor_name} is complete.",
    ]
    if order.fulfillment == "pickup":
        lines.append("We hope you enjoyed your pickup. Thanks for ordering with us!")
    else:
        lines.append("Your delivery is on its way. Thanks for ordering with us!")
    lines += [
        "",
        f"Order total: ${float(order.total):.2f}",
        "",
        "Shukran! 🇪🇬",
        f"— {vendor_name}",
    ]
    return subject, "\n".join(lines)


def _serialize(order: models.Order) -> schemas.OrderOut:
    # points_discount is nullable (old rows carry NULL); the API always
    # reports a number.
    if order.points_discount is None:
        order.points_discount = Decimal("0")
    out = schemas.OrderOut.model_validate(order)
    out.customer_name = order.customer.name if order.customer else (order.guest_name or "")
    out.vendor_name = order.vendor.name if order.vendor else ""
    return out




_FISH_SIDE_CHOICES = [{"label":"Rice","delta":0},{"label":"French fries","delta":0},{"label":"Tahini salad","delta":0},{"label":"Egyptian salad","delta":0}]

def _default_fish_sides(dish: models.Dish) -> bool:
    return dish.name.strip().casefold() == "whole grilled fish" and float(dish.price) == 18.0

def _fish_sides_group(dish: models.Dish, option_id: int) -> models.DishOption:
    return models.DishOption(
        id=option_id, dish_id=dish.id, name="Sides", selection_type="multiple",
        min_select=0, max_select=None, choices=json.dumps(_FISH_SIDE_CHOICES),
    )

def _modifier_options(
    db: Session,
    dish_ids: list[int],
    dishes: dict[int, models.Dish] | None = None,
) -> dict[int, list[models.DishOption]]:
    """All modifier groups plus transient built-in fish sides for order validation."""
    by_dish: dict[int, list[models.DishOption]] = {}
    for o in db.scalars(
        select(models.DishOption)
        .where(models.DishOption.dish_id.in_(dish_ids))
        .order_by(models.DishOption.id)
    ).all():
        by_dish.setdefault(o.dish_id, []).append(o)
    if dishes:
        for dish_id in dish_ids:
            dish = dishes.get(dish_id)
            if dish is None or not _default_fish_sides(dish):
                continue
            groups = by_dish.get(dish_id, [])
            side_idx = next((i for i, g in enumerate(groups) if (g.name or "").strip().casefold() == "sides"), None)
            if side_idx is None:
                groups = groups + [_fish_sides_group(dish, -dish.id)]
            else:
                groups = list(groups)
                groups[side_idx] = _fish_sides_group(dish, groups[side_idx].id)
            by_dish[dish_id] = groups
    return by_dish


def _dish_ingredients(
    db: Session,
    dish_ids: list[int],
    dishes: dict[int, models.Dish] | None = None,
) -> dict[int, list[models.DishIngredient]]:
    """All customizable ingredients per dish, keyed by dish_id (id order).

    Fallback (v41 fix): a dish with NO managed rows gets pseudo-rows parsed
    from its free-text `ingredients` — exactly what the customer frontends
    offer as toggles when no managed rows exist (see dishIngredients() in
    frontend/app.js: comma-split, trimmed, deduped, first 30, each treated
    as included-by-default and removable at no extra charge). Without this,
    validation rejected every such toggle with "Unknown ingredient" and the
    order could not be placed at all (e.g. removing 'garlic' from
    'Whole Grilled Fish'). Pseudo-rows are transient (never persisted) and
    priced from the server side (0), never from the client."""
    by_dish: dict[int, list[models.DishIngredient]] = {}
    for ing in db.scalars(
        select(models.DishIngredient)
        .where(models.DishIngredient.dish_id.in_(dish_ids))
        .order_by(models.DishIngredient.id)
    ).all():
        by_dish.setdefault(ing.dish_id, []).append(ing)
    if dishes:
        for dish_id in dish_ids:
            if by_dish.get(dish_id):
                continue
            dish = dishes.get(dish_id)
            if dish is None or not dish.ingredients:
                continue
            seen: set[str] = set()
            for raw in str(dish.ingredients).split(","):
                nm = raw.strip()
                if not nm or nm in seen:
                    continue
                seen.add(nm)
                by_dish.setdefault(dish_id, []).append(
                    models.DishIngredient(
                        dish_id=dish_id,
                        name=nm,
                        included_by_default=True,
                        removable=True,
                        extra_price=0,
                    )
                )
                if len(by_dish[dish_id]) >= 30:
                    break
    return by_dish


def _option_choices(option: models.DishOption) -> list[dict]:
    try:
        choices = json.loads(option.choices or "[]")
    except (ValueError, TypeError):
        choices = []
    return [c for c in choices if isinstance(c, dict)]


def _money(delta: Decimal) -> str:
    sign = "+" if delta >= 0 else "-"
    return f"{sign}${abs(delta):.2f}"


def _resolve_customization(
    dish: models.Dish,
    groups: list[models.DishOption],
    ingredients: list[models.DishIngredient],
    item: schemas.OrderItemIn,
) -> tuple[Decimal, str | None, list[dict] | None, list[str], list[str], Decimal]:
    """Validate a line item's modifiers + ingredient customization, tamper-proof.

    Returns (modifier_delta, modifier_label, modifier_detail, removed_names,
    added_names, added_extra). Every label must match a configured choice
    EXACTLY (case-sensitive); every price delta is taken from the DATABASE —
    client-sent prices are never trusted. Raises HTTPException(400) on any
    tampering or missing required group.
    """
    # ---- Phase 1: resolve what the client submitted per group ----
    # submitted: option_id -> (group, labels)
    submitted: dict[int, tuple[models.DishOption, list[str]]] = {}
    if item.modifiers is not None:
        # New multi-group contract: labels only, deltas come from the DB.
        by_id = {g.id: g for g in groups}
        for m in item.modifiers:
            group = by_id.get(m.option_id)
            if group is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown modifier group for '{dish.name}'",
                )
            if group.id in submitted:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate modifier group '{group.name}' for '{dish.name}'",
                )
            submitted[group.id] = (group, list(m.choice_labels))
    elif item.modifier is not None:
        # Legacy single-group contract (mobile app): label AND delta must
        # match a choice exactly. Resolves against the dish's single-choice
        # group(s), first exact match wins.
        singles = [g for g in groups if (g.selection_type or "single") == "single"]
        if not singles:
            raise HTTPException(
                status_code=400,
                detail=f"Dish '{dish.name}' has no modifiers",
            )
        want_label = item.modifier.choice_label.strip()
        want_delta = Decimal(str(item.modifier.delta))
        matched: tuple[models.DishOption, str] | None = None
        for group in singles:
            for c in _option_choices(group):
                try:
                    if str(c.get("label", "")) == want_label and Decimal(str(c.get("delta"))) == want_delta:
                        matched = (group, want_label)
                        break
                except Exception:  # noqa: BLE001 — malformed stored choice: skip it
                    continue
            if matched is not None:
                break
        if matched is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid modifier for '{dish.name}'",
            )
        group, label = matched
        submitted[group.id] = (group, [label])
    # Required groups: any group with min_select >= 1 must be submitted.
    for group in groups:
        if (group.min_select or 0) >= 1 and group.id not in submitted:
            raise HTTPException(
                status_code=400,
                detail=f"Dish '{dish.name}' requires '{group.name}' — please choose.",
            )

    # ---- Phase 2: validate each submitted group, price from the DB ----
    total_delta = Decimal("0")
    segments: list[str] = []
    detail: list[dict] = []
    for group, labels in submitted.values():
        by_label: dict[str, Decimal] = {}
        for c in _option_choices(group):
            try:
                lbl = str(c.get("label", ""))
                if lbl not in by_label:  # first occurrence wins (matches legacy matcher)
                    by_label[lbl] = Decimal(str(c.get("delta", 0)))
            except Exception:  # noqa: BLE001 — malformed stored choice: skip it
                continue
        stype = group.selection_type or "single"
        min_sel = group.min_select or 0
        max_sel = group.max_select  # None = unbounded
        if stype == "single":
            if len(labels) != 1:
                raise HTTPException(
                    status_code=400,
                    detail=f"Option '{group.name}' needs exactly one choice",
                )
        else:
            n = len(labels)
            if n < min_sel:
                raise HTTPException(
                    status_code=400,
                    detail=f"Option '{group.name}' needs at least {min_sel} choice(s)",
                )
            if max_sel is not None and n > max_sel:
                raise HTTPException(
                    status_code=400,
                    detail=f"Option '{group.name}' allows at most {max_sel} choice(s)",
                )
        if len(set(labels)) != len(labels):
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate choice in '{group.name}'",
            )
        group_delta = Decimal("0")
        parts: list[str] = []
        deltas: list[float] = []
        for label in labels:
            if label not in by_label:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid choice '{label}' for '{group.name}'",
                )
            d = by_label[label]
            group_delta += d
            deltas.append(float(d))
            parts.append(f"{label} ({_money(d)})")
        total_delta += group_delta
        segments.append(f"{group.name}: {', '.join(parts)}")
        detail.append(
            {
                "option_id": group.id,
                "option_name": group.name,
                "labels": list(labels),
                "deltas": deltas,
            }
        )

    # ---- Phase 3: ingredient customization ----
    by_name: dict[str, models.DishIngredient] = {}
    for ing in ingredients:
        by_name.setdefault(ing.name, ing)
    removed: list[str] = []
    for name in item.removed_ingredients or []:
        ing = by_name.get(name)
        if ing is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown ingredient '{name}' for '{dish.name}'",
            )
        if not ing.included_by_default or not ing.removable:
            raise HTTPException(
                status_code=400,
                detail=f"Ingredient '{name}' cannot be removed from '{dish.name}'",
            )
        if name not in removed:
            removed.append(name)
    added: list[str] = []
    added_extra = Decimal("0")
    for name in item.added_ingredients or []:
        ing = by_name.get(name)
        if ing is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown ingredient '{name}' for '{dish.name}'",
            )
        if ing.included_by_default:
            raise HTTPException(
                status_code=400,
                detail=f"Ingredient '{name}' is already included in '{dish.name}'",
            )
        if name not in added:
            added.append(name)
            added_extra += Decimal(str(ing.extra_price or 0))

    label = "; ".join(segments) if segments else None
    return (
        total_delta,
        label,
        detail or None,
        removed,
        added,
        added_extra,
    )


def _prepare_order(
    db: Session,
    user: models.User | None,
    *,
    vendor_id: int,
    items: list[schemas.OrderItemIn],
    fulfillment: str,
    pickup_at,
    delivery_address: str | None,
    payment_method: str,
    notes: str | None,
    checkout_group: str | None,
    guest: schemas.GuestInfo | None = None,
    promo_code: str | None = None,
    promo_percent: int = 0,
    points_discount: Decimal = Decimal("0"),
    referral_code: str | None = None,  # === FEATURE 2: referral share link ===
    pickup_slot_id: int | None = None,  # === FEATURE 8: weekly pickup slot ===
    delivery_zip: str | None = None,  # === v29: customer delivery ZIP ===
    drop_id: int | None = None,  # === Community drops (Oct 2026): batch drop id ===
) -> models.Order:
    """Validate and build ONE order without committing.

    Shared by the single-order endpoint, the multi-vendor checkout, and the
    guest checkout so the pricing/validation rules (discount effective-price,
    promo, stock caps, modifiers) live in exactly one place.
    `user` is None for guest checkout — then `guest` (name/phone) is required.
    `referral_code` (FEATURE 2) is SERVER-resolved to a real vendor; unknown
    codes are ignored — client-side attribution is never trusted.
    Raises HTTPException on any validation failure.
    """
    if user is None:
        if guest is None or not (guest.name or "").strip() or not (guest.phone or "").strip():
            raise HTTPException(status_code=400, detail="Guest name and phone are required")
        placed_by = guest.name
    else:
        placed_by = user.name

    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Shop hours + pause switch: friendly 400 including when they reopen.
    is_open, open_msg = vendor_open_status(vendor)
    if not is_open:
        raise HTTPException(status_code=400, detail=open_msg)

    # === v48: direct-pay pause (weekly commission automation). While a
    # shop's direct payments are paused for unpaid commission, cash /
    # Zelle / Venmo orders are rejected; card + wallet methods still work.
    # Every create path (single, multi, guest) funnels through here. ===
    if getattr(vendor, "direct_pay_paused", False) and is_direct_payment_method(payment_method):
        raise HTTPException(
            status_code=400,
            detail="Direct payments are paused for this shop — please pay by card or contact the shop",
        )
    # === END v48 ===

    if fulfillment == "delivery" and vendor.fulfillment == "pickup":
        raise HTTPException(status_code=400, detail="This vendor is pickup only")
    if fulfillment == "pickup" and vendor.fulfillment == "delivery":
        raise HTTPException(status_code=400, detail="This vendor is delivery only")
    if fulfillment == "pickup" and pickup_at is None:
        raise HTTPException(status_code=400, detail="Pickup date/time is required for pickup orders")
    if fulfillment == "delivery" and not (delivery_address or "").strip():
        raise HTTPException(status_code=400, detail="Delivery address is required for delivery orders")
    # === v29: delivery zones — the customer ZIP must be 5 digits and inside
    # the vendor's delivery_zips zones. Blank/NULL zones = pickup only. ===
    delivery_zip_snapshot: str | None = None
    if fulfillment == "delivery":
        dzip = (delivery_zip or "").strip()
        # ASCII digits only: .isdigit() also matches Arabic-Indic etc.
        if not (dzip.isascii() and dzip.isdigit() and len(dzip) == 5):
            raise HTTPException(
                status_code=422,
                detail="A 5-digit delivery ZIP code is required for delivery orders",
            )
        zones = [z.strip() for z in (vendor.delivery_zips or "").split(",") if z.strip()]
        if not zones or dzip not in zones:
            raise HTTPException(
                status_code=422,
                detail=f"Sorry — {vendor.name} doesn't deliver to {dzip}",
            )
        delivery_zip_snapshot = dzip
    # === END v29 ===

    # === FEATURE 8: vendor weekly pickup slots ===
    slot_id_snapshot: int | None = None
    slot_label_snapshot: str | None = None
    if pickup_slot_id is not None and fulfillment == "delivery":
        raise HTTPException(status_code=400, detail="Pickup slots are for pickup orders only")
    if fulfillment == "pickup":
        active_slots = list(
            db.scalars(
                select(models.PickupSlot)
                .where(
                    models.PickupSlot.vendor_id == vendor.id,
                    models.PickupSlot.active.is_(True),
                )
                .order_by(models.PickupSlot.weekday, models.PickupSlot.start_time)
            ).all()
        )
        pickup_at, slot = _validate_pickup_time(
            vendor,
            pickup_at,
            active_slots=active_slots,
            pickup_slot_id=pickup_slot_id,
        )
        if slot is not None:
            slot_id_snapshot = slot.id
            slot_label_snapshot = slot_label_with_date(
                slot,
                on=pickup_at.replace(tzinfo=dt.timezone.utc).astimezone(_MARKET_TZ).date(),
            )
    # === END FEATURE 8 ===

    # === Community drops (Oct 2026): the customer joins a vendor's
    # scheduled batch drop-off. Validated server-side: the drop must exist,
    # belong to this vendor, be active, not be in the past, cover the
    # customer's 5-digit ZIP, and not be full. Drops are free like pickup
    # (no delivery fee). ===
    drop_snapshot: models.DeliveryDrop | None = None
    drop_label_snapshot: str | None = None
    if fulfillment == "drop":
        if drop_id is None:
            raise HTTPException(status_code=400, detail="Please choose a community drop")
        drop = db.get(models.DeliveryDrop, drop_id)
        if drop is None or drop.vendor_id != vendor.id:
            raise HTTPException(status_code=400, detail="Invalid community drop for this vendor")
        if not drop.is_active:
            raise HTTPException(status_code=400, detail="This community drop is no longer active")
        if drop.drop_date is None or drop.drop_date < dt.date.today():
            raise HTTPException(status_code=400, detail="This community drop has already happened")
        dzip = (delivery_zip or "").strip()
        # ASCII digits only: .isdigit() also matches Arabic-Indic etc.
        if not (dzip.isascii() and dzip.isdigit() and len(dzip) == 5):
            raise HTTPException(
                status_code=422,
                detail="A 5-digit ZIP code is required for community drop orders",
            )
        zones = [z.strip() for z in (drop.zip_codes or "").split(",") if z.strip()]
        if not zones or dzip not in zones:
            raise HTTPException(
                status_code=422,
                detail=f"Sorry — this community drop doesn't serve {dzip}",
            )
        if drop.max_orders is not None:
            # === Security P1 (Oct 2026): TOCTOU lock — take a row lock on the
            # drop BEFORE counting riders, inside the checkout transaction.
            # This serializes the count-then-insert so concurrent checkouts
            # can't overfill the drop. Matches the atomic conditional UPDATE
            # pattern used for stock (line ~113) and promos. SQLite
            # serializes writers anyway, so this is a no-op there and correct
            # on Postgres. _prepare_order always runs inside the checkout
            # transaction (checkout-multi is all-or-nothing; create_order
            # commits after), so the lock participates. ===
            drop = (
                db.query(models.DeliveryDrop)
                .filter(models.DeliveryDrop.id == drop.id)
                .with_for_update()
                .one()
            )
            riding = db.scalar(
                select(func.count()).where(
                    models.Order.drop_id == drop.id,
                    models.Order.status != "cancelled",
                )
            ) or 0
            if riding >= drop.max_orders:
                raise HTTPException(status_code=422, detail="This community drop is full")
        drop_snapshot = drop
        drop_label_snapshot = drop.label
        delivery_zip_snapshot = dzip
    # === END community drops ===

    dish_ids = [i.dish_id for i in items if i.dish_id is not None]
    dishes = {d.id: d for d in db.scalars(select(models.Dish).where(models.Dish.id.in_(dish_ids)))}
    options = _modifier_options(db, dish_ids, dishes)
    ingredients = _dish_ingredients(db, dish_ids, dishes)
    # === FEATURE 5: bundle line items (priced ONLY at the bundle's fixed price) ===
    bundle_ids = [i.bundle_id for i in items if i.bundle_id is not None]
    bundles: dict[int, models.Bundle] = {}
    if bundle_ids:
        bundles = {
            b.id: b
            for b in db.scalars(
                select(models.Bundle)
                .options(
                    joinedload(models.Bundle.items).joinedload(models.BundleItem.dish)
                )
                .where(models.Bundle.id.in_(bundle_ids))
            ).unique().all()
        }
    # === END FEATURE 5 ===
    subtotal = Decimal("0")
    line_items: list[models.OrderItem] = []
    sold: list[tuple[models.Dish, int]] = []  # (dish, qty) for sale movements
    for item in items:
        # === FEATURE 5: bundle line — server prices at bundle.price; the
        # component dishes are display-only (names in the snapshot label)
        # and never re-priced. Cross-vendor bundles are rejected.
        if item.bundle_id is not None:
            bundle = bundles.get(item.bundle_id)
            if bundle is None:
                raise HTTPException(status_code=404, detail=f"Bundle {item.bundle_id} not found")
            if bundle.vendor_id != vendor.id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Bundle '{bundle.name}' does not belong to this vendor",
                )
            if not bundle.available:
                raise HTTPException(
                    status_code=400,
                    detail=f"Bundle '{bundle.name}' is not available",
                )
            # === v29: holiday feasts — an ended bundle can't be ordered. ===
            if _bundle_ended(db, bundle):
                raise HTTPException(
                    status_code=422,
                    detail=f"Bundle '{bundle.name}' is no longer available for ordering",
                )
            # === END v29 ===
            price = Decimal(str(bundle.price))
            subtotal += price * item.quantity
            comp_parts = []
            for bi in bundle.items or []:
                nm = bi.dish.name if bi.dish else "?"
                comp_parts.append(nm if (bi.quantity or 1) == 1 else f"{nm} ×{bi.quantity}")
            line_items.append(
                models.OrderItem(
                    dish_id=None,
                    bundle_id=bundle.id,
                    dish_name=bundle.name,
                    unit_price=price,
                    quantity=item.quantity,
                    modifier_label=("🍱 " + ", ".join(comp_parts)) if comp_parts else None,
                )
            )
            continue
        # === END FEATURE 5 ===
        dish = dishes.get(item.dish_id)
        if dish is None:
            raise HTTPException(status_code=404, detail=f"Dish {item.dish_id} not found")
        if dish.vendor_id != vendor.id:
            raise HTTPException(status_code=400, detail=f"Dish '{dish.name}' does not belong to this vendor")
        if not dish.available:
            raise HTTPException(status_code=400, detail=f"Dish '{dish.name}' is not available")
        # Advance ordering / weekly specials (Oct 2026): the order window is
        # evaluated in America/Los_Angeles and re-checked here at checkout so
        # a stale client can't order outside it. 400 with a friendly message.
        window = dish_order_window(dish)
        if not window["open"]:
            raise HTTPException(
                status_code=400,
                detail=order_window_block_message(dish.name, window),
            )
        # Stock cap: NULL = unlimited. Decremented with an ATOMIC
        # conditional UPDATE (DBA P0-2): the old read-check-write let two
        # concurrent checkouts both read stock=1, both pass, both
        # decrement — overselling on Postgres. The WHERE clause is the
        # cap check; rowcount 0 means another checkout grabbed the last
        # units (or the dish went out of stock). The ORM object is
        # expired so later reads (stock_after on the movement) see the
        # post-update value; it is never assigned, so a later flush
        # cannot overwrite the DB value with a stale one. A failed
        # validation later in this function rolls the UPDATE back too —
        # checkout stays all-or-nothing.
        if dish.stock_quantity is not None:
            result = db.execute(
                update(models.Dish)
                .where(
                    models.Dish.id == dish.id,
                    models.Dish.stock_quantity >= item.quantity,
                )
                .values(stock_quantity=models.Dish.stock_quantity - item.quantity)
            )
            if result.rowcount != 1:
                db.expire(dish, ["stock_quantity"])
                raise HTTPException(
                    status_code=422,
                    detail=f"Only {dish.stock_quantity} left of '{dish.name}'",
                )
            db.expire(dish, ["stock_quantity"])
            sold.append((dish, item.quantity))
        delta, modifier_label, modifier_detail, removed, added, added_extra = _resolve_customization(
            dish, options.get(dish.id, []), ingredients.get(dish.id, []), item
        )
        # Effective price: the discount is applied here so the customer is
        # charged the sale price, and the snapshot keeps it for history.
        # Modifiers and added-ingredient extras are priced from the DB.
        # F7: the discount is flash-sale-aware — while a flash sale is live
        # the effective discount is max(standing, flash); expired windows
        # fall back to the standing discount automatically.
        disc = flash_sales.effective_discount_percent(dish)
        price = round(
            Decimal(dish.price) * (Decimal(1) - Decimal(disc) / Decimal(100)) + delta + added_extra, 2
        )
        subtotal += price * item.quantity
        line_items.append(
            models.OrderItem(
                dish_id=dish.id,
                dish_name=dish.name,
                # v52: Arabic name snapshot (NULL when the dish has none).
                dish_name_ar=dish.name_ar,
                unit_price=price,
                quantity=item.quantity,
                modifier_label=modifier_label,
                modifier_detail=json.dumps(modifier_detail) if modifier_detail else None,
                removed_ingredients=json.dumps(removed) if removed else None,
                added_ingredients=json.dumps(added) if added else None,
            )
        )

    # === FEATURE 2: referral attribution ===
    # The SERVER resolves the code to a real vendor. Unknown/blank codes are
    # ignored — they never crash the checkout and are never trusted.
    attr_vendor = referrals.resolve_referral(db, referral_code)
    # === END FEATURE 2 ===
    discount = (
        round(subtotal * Decimal(promo_percent) / Decimal(100), 2)
        if promo_code and promo_percent
        else Decimal("0")
    )
    delivery_fee = Decimal(vendor.delivery_fee) if fulfillment == "delivery" else Decimal("0")
    # === v46: free delivery over the vendor's threshold. Compares the
    # items subtotal BEFORE promo/points discounts (the `subtotal` above);
    # a threshold of 0 waives the fee on every delivery order. ===
    if (
        fulfillment == "delivery"
        and vendor.free_delivery_over is not None
        and subtotal >= Decimal(vendor.free_delivery_over)
    ):
        delivery_fee = Decimal("0")
    # === END v46 ===
    tax = (subtotal * _current_tax_rate(db)).quantize(Decimal("0.01"))
    # Snapshot the applicable commission at order creation. Cash/Zelle/Venmo
    # remain direct-to-vendor methods; the receivable is collected separately.
    rate_row = db.scalar(
        select(models.Setting).where(models.Setting.key == "commission_percent")
    )
    try:
        default_commission_rate = Decimal(str(rate_row.value)) if rate_row is not None else Decimal("0")
    except (ValueError, TypeError):
        default_commission_rate = Decimal("0")
    commission_rate = (
        Decimal(str(vendor.commission_rate))
        if vendor.commission_rate is not None
        else default_commission_rate
    )
    order_total = subtotal - discount - points_discount + delivery_fee + tax
    commissionable_food_subtotal = max(
        Decimal("0.00"), subtotal - discount - points_discount
    )
    commission_due = commission_for_amount(commissionable_food_subtotal, commission_rate)
    order = models.Order(
        customer_id=user.id if user is not None else None,
        vendor_id=vendor.id,
        status="new",
        fulfillment=fulfillment,
        pickup_at=pickup_at,
        delivery_address=(delivery_address or "").strip() or None,
        payment_method=payment_method,  # recorded only — nothing is charged
        notes=(notes or "").strip() or None,
        checkout_group=checkout_group,
        promo_code=promo_code,
        discount_amount=discount,
        points_discount=points_discount,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        tax=tax,
        total=order_total,
        commission_due=commission_due,
        guest_name=guest.name if guest is not None else None,
        guest_phone=guest.phone if guest is not None else None,
        # === FEATURE 2: referral attribution — server-validated only ===
        referral_code=attr_vendor.referral_code if attr_vendor else None,
        attributed_vendor_id=attr_vendor.id if attr_vendor else None,
        # === END FEATURE 2 ===
        # === FEATURE 8: chosen weekly pickup slot snapshot ===
        pickup_slot_id=slot_id_snapshot,
        pickup_slot_label=slot_label_snapshot,
        # === END FEATURE 8 ===
        # === v29: customer delivery ZIP (validated against zones above) ===
        delivery_zip=delivery_zip_snapshot,
        # === END v29 ===
        # === Community drops (Oct 2026): batch drop id + denormalized label
        # (the label snapshot survives the vendor deleting the drop) ===
        drop_id=drop_snapshot.id if drop_snapshot else None,
        drop_label=drop_label_snapshot,
        # === END community drops ===
        items=line_items,
    )
    db.add(order)
    db.flush()  # assign order.id before logging
    # Stock history: one 'sale' movement per decremented dish.
    for dish, qty in sold:
        _record_stock_movement(db, dish, -qty, "sale", order.id)
    _log_event(
        db, order, "placed",
        f"Order placed by {placed_by} — {len(line_items)} item(s), "
        f"{fulfillment}, paid via {payment_method} (recorded only)",
        {"fulfillment": fulfillment, "payment_method": payment_method,
         "checkout_group": checkout_group, "promo_code": promo_code,
         "guest": user is None,
         "referral_code": attr_vendor.referral_code if attr_vendor else None,
         "attributed_vendor_id": attr_vendor.id if attr_vendor else None},
    )
    # === v44: loyalty points are earned at PLACEMENT (not completion) ===
    # One call site covers every create path (single, multi, guest — the
    # helper skips guests). The helper never raises and only flushes, so a
    # rolled-back checkout takes the earn with it.
    earned = loyalty.award_order_points(db, order)
    if earned:
        _log_event(
            db, order, "points",
            f"Awarded {earned} loyalty points",
            {"points": earned},
        )
    return order


@router.post("", response_model=schemas.OrderOut, status_code=201)
def create_order(
    payload: schemas.OrderCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    if user.role not in ("customer", "vendor", "admin"):
        raise HTTPException(status_code=403, detail="Only customers can place orders")

    order = _prepare_order(
        db, user,
        vendor_id=payload.vendor_id,
        items=payload.items,
        fulfillment=payload.fulfillment,
        pickup_at=payload.pickup_at,
        delivery_address=payload.delivery_address,
        payment_method=payload.payment_method,
        notes=payload.notes,
        checkout_group=None,
        referral_code=payload.referral_code,  # === FEATURE 2 ===
        pickup_slot_id=payload.pickup_slot_id,  # === FEATURE 8 ===
        delivery_zip=payload.delivery_zip,  # === v29 ===
        drop_id=payload.drop_id,  # === Community drops (Oct 2026) ===
    )
    db.commit()
    db.refresh(order)
    # Order confirmation email (real send if a mail provider is configured,
    # otherwise a clearly-marked console log). Never breaks the order.
    try:
        sent = emailer.send_order_confirmation(order)
        _log_event(
            db, order, "email",
            f"Confirmation email sent to {order.customer.email if order.customer else 'customer'}",
            {"to": order.customer.email if order.customer else "", "sent": sent},
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] confirmation email failed: {exc}")
    # === v40: admin alert (push + SMS, toggleable). Never breaks the order. ===
    try:
        notifier.alert_admins(
            db, "order",
            f"New order #{order.id} — ${float(order.total):.2f}",
            f"New order #{order.id} from {order.vendor.name if order.vendor else ''} — ${float(order.total):.2f}\nطلب جديد رقم #{order.id} بقيمة ${float(order.total):.2f}",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] admin alert failed: {exc}")
    return _serialize(order)


def _apply_points_redemption(
    db: Session,
    user: models.User,
    orders: list[models.Order],
    requested_points: int,
    group_id: str,
) -> tuple[int, Decimal]:
    """Apply loyalty-points redemption across the sub-orders, same transaction.

    Discount dollars = points / points_per_dollar_redeem, capped at each
    sub-order's remaining total AND at the customer's points balance.
    The discount fills sub-orders sequentially (first group first); points
    are whole and dollars are rounded DOWN to the cent, so the discount can
    never exceed what the customer owes. The balance is deducted and one
    reason='redeem' ledger row is written per sub-order that absorbed points.

    Returns (points_used, total_dollars_off).
    """
    rate = loyalty.get_setting(db, "points_per_dollar_redeem", 50)
    balance = user.points_balance or 0
    remaining = min(requested_points, balance)
    used = 0
    dollars = Decimal("0")
    for order in orders:
        if remaining <= 0:
            break
        cap = min(Decimal(order.subtotal or 0), Decimal(order.total or 0))
        alloc = min(cap, Decimal(remaining) / Decimal(rate)).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        pts = int(alloc * rate)
        if pts <= 0:
            continue
        # Re-derive dollars from whole points so the ledger and the order agree.
        alloc = (Decimal(pts) / Decimal(rate)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        order.points_discount = (order.points_discount or Decimal("0")) + alloc
        order.total = Decimal(order.total) - alloc
        # Loyalty redemption is applied after the vendor order is created;
        # refresh the commission snapshot so points discounts reduce the
        # commissionable food subtotal just like promo discounts do.
        order.commission_due = commission_for_amount(
            commissionable_food_amount(order),
            _commission_rate_for_order(db, order),
        )
        db.add(
            models.LoyaltyLedger(
                user_id=user.id,
                order_id=order.id,
                delta=-pts,
                reason=loyalty.REDEEM,
                note=f"Redeemed at checkout (group {group_id[:8]})",
            )
        )
        _log_event(
            db, order, "points",
            f"Redeemed {pts} loyalty points (-${alloc:.2f})",
            {"points": pts, "discount": str(alloc)},
        )
        remaining -= pts
        used += pts
        dollars += alloc
    if used:
        # Atomic balance decrement (DBA P1-2): two concurrent checkouts
        # could both read the same balance and both redeem it. The WHERE
        # guard fails the second checkout (rowcount 0 → 400 → the caller
        # rolls the whole checkout back) instead of overdrawing.
        result = db.execute(
            update(models.User)
            .where(
                models.User.id == user.id,
                func.coalesce(models.User.points_balance, 0) >= used,
            )
            .values(points_balance=func.coalesce(models.User.points_balance, 0) - used)
        )
        if result.rowcount != 1:
            raise HTTPException(
                status_code=400,
                detail="Loyalty points balance changed — please retry checkout",
            )
        db.expire(user, ["points_balance"])
    db.flush()
    return used, dollars


@router.post("/checkout-multi", response_model=schemas.CheckoutMultiOut, status_code=201)
def checkout_multi(
    payload: schemas.CheckoutMultiIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """One cart, one payment, split into one order per vendor — atomically.

    All sub-orders are created in a single transaction: if any group fails
    validation, NOTHING is created (all-or-nothing). Sub-orders share a
    checkout_group UUID so they can be shown together. A promo code is
    validated ONCE for the whole checkout and applied per sub-order.
    """
    if user.role not in ("customer", "vendor", "admin"):
        raise HTTPException(status_code=403, detail="Only customers can place orders")
    check_rate_limit(request, "checkout_multi", limit=20, window_seconds=3600)

    # Validate the promo once (400 with the reason if invalid) — it is only
    # consumed (used_count += 1) if the whole checkout succeeds.
    promo_code: str | None = None
    promo_percent = 0
    promo = None
    if payload.promo_code:
        promo, reason = validate_promo(db, payload.promo_code)
        if promo is None:
            raise HTTPException(status_code=400, detail=f"Promo code invalid: {reason}")
        promo_code = promo.code
        promo_percent = promo.percent_off

    group_id = str(uuid.uuid4())
    orders: list[models.Order] = []
    try:
        for g in payload.groups:
            orders.append(
                _prepare_order(
                    db, user,
                    vendor_id=g.vendor_id,
                    items=g.items,
                    fulfillment=g.fulfillment,
                    pickup_at=g.pickup_at,
                    delivery_address=g.delivery_address,
                    payment_method=payload.payment_method,
                    notes=g.notes,
                    checkout_group=group_id,
                    promo_code=promo_code,
                    promo_percent=promo_percent,
                    referral_code=payload.referral_code,  # === FEATURE 2 ===
                    pickup_slot_id=g.pickup_slot_id,  # === FEATURE 8 ===
                    delivery_zip=g.delivery_zip,  # === v29 ===
                    drop_id=g.drop_id,  # === Community drops (Oct 2026) ===
                )
            )
        if promo is not None:
            # Consumed exactly ONCE per successful checkout, not per sub-order.
            # Atomic conditional increment (DBA P1-1): the old
            # read-modify-write let two concurrent checkouts both read
            # used_count=9 (max 10), both write 10 — 11 redemptions.
            # rowcount 0 = the cap was hit concurrently → 400, and the
            # caller rolls the whole checkout back.
            result = db.execute(
                update(models.PromoCode)
                .where(
                    models.PromoCode.id == promo.id,
                    or_(
                        models.PromoCode.max_uses.is_(None),
                        func.coalesce(models.PromoCode.used_count, 0) < models.PromoCode.max_uses,
                    ),
                )
                .values(used_count=func.coalesce(models.PromoCode.used_count, 0) + 1)
            )
            if result.rowcount != 1:
                raise HTTPException(
                    status_code=400,
                    detail="Promo code has reached its maximum uses",
                )
            db.expire(promo, ["used_count"])
        # Loyalty redemption (accounts only): discounted per sub-order,
        # balance deducted and ledger written in this same transaction.
        points_discount_total = Decimal("0")
        if payload.redeem_points and payload.redeem_points > 0:
            _, points_discount_total = _apply_points_redemption(
                db, user, orders, payload.redeem_points, group_id
            )
        db.commit()
    except HTTPException:
        # Validation (or anything else) failed part-way: roll everything back
        # so the customer never ends up with a partial checkout.
        db.rollback()
        raise
    for order in orders:
        db.refresh(order)
    # One confirmation email per sub-order (same as single checkout), plus a
    # new-order notification to each vendor owner. Never breaks the orders —
    # they are already committed, and each email is individually best-effort.
    try:
        for order in orders:
            sent = emailer.send_order_confirmation(order)
            _log_event(
                db, order, "email",
                f"Confirmation email sent to {order.customer.email if order.customer else 'customer'}",
                {"to": order.customer.email if order.customer else "", "sent": sent,
                 "checkout_group": group_id},
            )
            vendor_sent = emailer.send_vendor_new_order_email(order)
            _log_event(
                db, order, "email",
                f"New-order notification sent to vendor "
                f"{order.vendor.name if order.vendor else 'vendor'}",
                {"sent": vendor_sent, "checkout_group": group_id},
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] confirmation email failed: {exc}")
    # === v40: admin alert per sub-order (push + SMS, toggleable). ===
    try:
        for order in orders:
            notifier.alert_admins(
                db, "order",
                f"New order #{order.id} — ${float(order.total):.2f}",
                f"New order #{order.id} from {order.vendor.name if order.vendor else ''} — ${float(order.total):.2f}\nطلب جديد رقم #{order.id} بقيمة ${float(order.total):.2f}",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] admin alert failed: {exc}")
    grand_total = sum((o.total for o in orders), Decimal("0"))
    return schemas.CheckoutMultiOut(
        checkout_group=group_id,
        orders=[_serialize(o) for o in orders],
        grand_total=grand_total,
        points_discount=points_discount_total,
    )


@router.post("/checkout-guest", response_model=schemas.CheckoutMultiOut, status_code=201)
def checkout_guest(
    payload: schemas.GuestCheckoutIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Guest checkout: no account needed. Same multi-vendor groups as
    checkout_multi; creates orders with customer_id=None and the guest's
    name/phone on each order. Strictly rate-limited (10/hour per IP)."""
    check_rate_limit(request, "checkout_guest", limit=10, window_seconds=3600)

    promo_code: str | None = None
    promo_percent = 0
    promo = None
    if payload.promo_code:
        promo, reason = validate_promo(db, payload.promo_code)
        if promo is None:
            raise HTTPException(status_code=400, detail=f"Promo code invalid: {reason}")
        promo_code = promo.code
        promo_percent = promo.percent_off

    group_id = str(uuid.uuid4())
    orders: list[models.Order] = []
    try:
        for g in payload.groups:
            orders.append(
                _prepare_order(
                    db, None,
                    vendor_id=g.vendor_id,
                    items=g.items,
                    fulfillment=g.fulfillment,
                    pickup_at=g.pickup_at,
                    delivery_address=g.delivery_address,
                    payment_method=payload.payment_method,
                    notes=g.notes,
                    checkout_group=group_id,
                    guest=payload.guest,
                    promo_code=promo_code,
                    promo_percent=promo_percent,
                    referral_code=payload.referral_code,  # === FEATURE 2 ===
                    pickup_slot_id=g.pickup_slot_id,  # === FEATURE 8 ===
                    delivery_zip=g.delivery_zip,  # === v29 ===
                    drop_id=g.drop_id,  # === Community drops (Oct 2026) ===
                )
            )
        if promo is not None:
            # Atomic conditional increment (DBA P1-1) — see checkout_multi.
            result = db.execute(
                update(models.PromoCode)
                .where(
                    models.PromoCode.id == promo.id,
                    or_(
                        models.PromoCode.max_uses.is_(None),
                        func.coalesce(models.PromoCode.used_count, 0) < models.PromoCode.max_uses,
                    ),
                )
                .values(used_count=func.coalesce(models.PromoCode.used_count, 0) + 1)
            )
            if result.rowcount != 1:
                raise HTTPException(
                    status_code=400,
                    detail="Promo code has reached its maximum uses",
                )
            db.expire(promo, ["used_count"])
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    for order in orders:
        db.refresh(order)
    # Guest confirmation goes to the guest's email when they gave one; the
    # vendor still gets the new-order notification. Best-effort as always.
    try:
        for order in orders:
            guest_email = str(payload.guest.email) if payload.guest.email else ""
            sent = emailer.send_order_confirmation(
                order, to_email=guest_email or None, to_name=payload.guest.name
            )
            _log_event(
                db, order, "email",
                f"Guest confirmation email sent to {guest_email or 'no email given'}",
                {"to": guest_email, "sent": sent, "checkout_group": group_id,
                 "guest": True},
            )
            vendor_sent = emailer.send_vendor_new_order_email(order)
            _log_event(
                db, order, "email",
                f"New-order notification sent to vendor "
                f"{order.vendor.name if order.vendor else 'vendor'}",
                {"sent": vendor_sent, "checkout_group": group_id, "guest": True},
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] guest confirmation email failed: {exc}")
    # === v40: admin alert per sub-order (push + SMS, toggleable). ===
    try:
        for order in orders:
            notifier.alert_admins(
                db, "order",
                f"New order #{order.id} — ${float(order.total):.2f}",
                f"New guest order #{order.id} from {order.vendor.name if order.vendor else ''} — ${float(order.total):.2f}\nطلب جديد (زائر) رقم #{order.id} بقيمة ${float(order.total):.2f}",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] admin alert failed: {exc}")
    grand_total = sum((o.total for o in orders), Decimal("0"))
    return schemas.CheckoutMultiOut(
        checkout_group=group_id,
        orders=[_serialize(o) for o in orders],
        grand_total=grand_total,
    )


@router.get("", response_model=list[schemas.OrderOut])
def list_orders(
    vendor_id: int | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    stmt = (
        select(models.Order)
        .options(joinedload(models.Order.items), joinedload(models.Order.customer), joinedload(models.Order.vendor))
        .order_by(models.Order.created_at.desc())
    )
    if user.role == "vendor":
        if vendor_id is None:
            owned_ids = [v.id for v in user.vendors]
            stmt = stmt.where(models.Order.vendor_id.in_(owned_ids))
        else:
            vendor = db.get(models.Vendor, vendor_id)
            if vendor is None:
                raise HTTPException(status_code=404, detail="Vendor not found")
            auth.vendor_owned_by(vendor, user)
            stmt = stmt.where(models.Order.vendor_id == vendor_id)
    else:
        stmt = stmt.where(models.Order.customer_id == user.id)
    return [_serialize(o) for o in db.scalars(stmt).unique().all()]


@router.get("/{order_id}", response_model=schemas.OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if user.role == "vendor":
        if not any(v.id == order.vendor_id for v in user.vendors):
            raise HTTPException(status_code=403, detail="Not your order")
    elif order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")
    return _serialize(order)


@router.patch("/{order_id}/status", response_model=schemas.OrderOut)
def update_status(
    order_id: int,
    payload: schemas.OrderStatusUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if user.role == "vendor":
        if not any(v.id == order.vendor_id for v in user.vendors):
            raise HTTPException(status_code=403, detail="Not your order")
    else:
        # Customer self-service: a customer may cancel their OWN order while it
        # is still 'new'. Anything else from a customer → 403.
        if order.customer_id != user.id:
            raise HTTPException(status_code=403, detail="Not your order")
        if payload.status != "cancelled" or order.status != "new":
            raise HTTPException(status_code=403, detail="Only new orders can be cancelled by the customer")
        order.status = "cancelled"
        db.flush()
        _log_event(
            db, order, "status",
            "Cancelled by customer",
            {"from": "new", "to": "cancelled", "by": user.name, "by_role": "customer"},
        )
        # Loyalty: refund any redeemed points AND reverse the points earned at
        # placement (v44) — the helpers guard when there's nothing to do.
        refunded = loyalty.refund_redeemed_points(db, order)
        if refunded:
            _log_event(
                db, order, "points",
                f"Refunded {refunded} redeemed loyalty points (order cancelled)",
                {"points": refunded},
            )
        reversed_pts = loyalty.reverse_earn_points(db, order)
        if reversed_pts:
            _log_event(
                db, order, "points",
                f"Reversed {reversed_pts} earned loyalty points (order cancelled)",
                {"points": reversed_pts},
            )
        _stripe_refund_on_cancel(db, order)  # refunds only paid card orders; never breaks cancel
        # Stock: restore ordered quantities (cancel_restore). Runs once —
        # cancelling an already-cancelled order is rejected by the guard above.
        _restore_stock_on_cancel(db, order)
        db.commit()
        db.refresh(order)
        try:
            emailer.send_order_status_update(order, "new", "cancelled")
        except Exception as exc:  # noqa: BLE001
            print(f"[orders] status email failed: {exc}")
        return _serialize(order)

    target = payload.status
    previous = order.status
    err = _transition_error(order, target)
    if err:
        raise HTTPException(status_code=400, detail=err)
    order.status = target
    db.flush()
    _log_event(
        db, order, "status",
        f"Status changed: {previous} → {target}",
        {"from": previous, "to": target, "by": user.name},
    )
    if target == "cancelled":
        # P1-1 (2026-10-15 audit): a vendor cancelling a paid card order must
        # trigger the same Stripe refund flow as customer/admin cancels.
        _stripe_refund_on_cancel(db, order)  # refunds only paid card orders; never breaks cancel
        # Loyalty: refund any redeemed points AND reverse the points earned
        # at placement (v44), same as customer/admin cancels (owner decision
        # 2026-10-12) — the helpers guard when there's nothing to do.
        refunded = loyalty.refund_redeemed_points(db, order)
        if refunded:
            _log_event(
                db, order, "points",
                f"Refunded {refunded} redeemed loyalty points (order cancelled)",
                {"points": refunded},
            )
        reversed_pts = loyalty.reverse_earn_points(db, order)
        if reversed_pts:
            _log_event(
                db, order, "points",
                f"Reversed {reversed_pts} earned loyalty points (order cancelled)",
                {"points": reversed_pts},
            )
        # Stock: restore ordered quantities (cancel_restore). Runs once —
        # the state machine rejects cancelling an already-cancelled order.
        _restore_stock_on_cancel(db, order)
    if target == "completed":
        # Completion email to the customer (simulated in the demo build —
        # recorded in the order log; wire to a real mailer for production).
        subject, body = _completion_email(order)
        _log_event(
            db, order, "email",
            f"Completion email sent to {order.customer.email if order.customer else 'customer'}",
            {"subject": subject, "body": body, "to": order.customer.email if order.customer else ""},
        )
        # Loyalty safety net (v44): points are normally awarded at PLACEMENT
        # (see _prepare_order); this hook only pays out pre-v44 orders that
        # never earned. The helper's double-award guard keeps it exactly-once.
        earned = loyalty.award_order_points(db, order)
        if earned:
            _log_event(
                db, order, "points",
                f"Awarded {earned} loyalty points",
                {"points": earned},
            )
    db.commit()
    db.refresh(order)
    # Real status-change email (in addition to the logged demo email above).
    try:
        emailer.send_order_status_update(order, previous, target)
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] status email failed: {exc}")
    # SMS the customer about the status change — best effort, never breaks it.
    try:
        notifier.send_order_status_sms(db, order, target)
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] status SMS failed: {exc}")
    # Expo push to the customer's app devices — best effort, never breaks it.
    try:
        notifier.send_order_status_push(db, order, target)
    except Exception as exc:  # noqa: BLE001
        print(f"[orders] status push failed: {exc}")
    return _serialize(order)


@router.post("/{order_id}/delivery-photo", response_model=schemas.OrderOut)
def attach_delivery_photo(
    order_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Attach (or replace) the delivery handoff photo for an order.

    Only the vendor who owns the order (or the site admin). Delivery orders
    only, and only once the order is on_the_way or completed — the photo is
    proof of the handoff, shown to the customer on their order page.
    """
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if user.role == "admin":
        pass
    elif user.role == "vendor" and any(v.id == order.vendor_id for v in user.vendors):
        pass
    else:
        raise HTTPException(status_code=403, detail="Not your order")
    if order.fulfillment != "delivery":
        raise HTTPException(status_code=400, detail="Delivery photos are for delivery orders only")
    if order.status not in ("on_the_way", "completed"):
        raise HTTPException(
            status_code=400,
            detail="A delivery photo can be added once the order is on the way or completed",
        )
    # Same disk-fill guard as the other photo uploads: 20/hour per IP.
    check_rate_limit(request, "delivery_photo_upload", limit=20, window_seconds=3600)
    new_url = save_uploaded_photo(file)
    delete_uploaded_file(order.delivery_photo_url)
    order.delivery_photo_url = new_url
    db.commit()
    db.refresh(order)
    return _serialize(order)


@router.get("/{order_id}/events", response_model=list[schemas.OrderEventOut])
def list_events(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if user.role == "vendor":
        if not any(v.id == order.vendor_id for v in user.vendors):
            raise HTTPException(status_code=403, detail="Not your order")
    elif order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")
    return list(
        db.scalars(
            select(models.OrderEvent)
            .where(models.OrderEvent.order_id == order_id)
            .order_by(models.OrderEvent.created_at)
        ).all()
    )


# ---------- order messaging ----------
def _message_access(order: models.Order, user: models.User) -> None:
    """Only the order's customer, the order's vendor owner, or the admin may
    read/write the order's message thread."""
    if user.role == "admin":
        return
    if user.role == "vendor":
        if not any(v.id == order.vendor_id for v in user.vendors):
            raise HTTPException(status_code=403, detail="Not your order")
        return
    if order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")


@router.get("/{order_id}/messages", response_model=list[schemas.OrderMessageOut])
def list_messages(
    order_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    _message_access(order, user)
    return list(
        db.scalars(
            select(models.OrderMessage)
            .where(models.OrderMessage.order_id == order_id)
            .order_by(models.OrderMessage.created_at, models.OrderMessage.id)
        ).all()
    )


@router.post("/{order_id}/messages", response_model=schemas.OrderMessageOut, status_code=201)
def post_message(
    order_id: int,
    payload: schemas.OrderMessageIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    _message_access(order, user)
    msg = models.OrderMessage(
        order_id=order.id,
        sender_role=user.role,  # derived from the caller, never from the body
        text=payload.text,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


# === FEATURE 10: payment retry / resume checkout ===
RETRY_WINDOW_MINUTES = 30


@router.post("/{order_id}/retry-payment")
def retry_payment(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Resume a failed card payment without losing the cart.

    Creates a FRESH Stripe PaymentIntent for the order's STORED total — no
    re-pricing; promo, loyalty discounts, and item customizations stay
    exactly as the original order (they are already on it).

    Allowed only when payment_status='failed', the failure is at most 30
    minutes old, and the order is still new + unpaid. Only the order's own
    customer may call it. Without STRIPE_SECRET_KEY this returns the same
    clean 501 as the payment-intent endpoint. Cash orders never need retry.
    """
    if user.role not in ("customer", "vendor", "admin"):
        raise HTTPException(status_code=403, detail="Only customers can retry payment")
    check_rate_limit(request, "stripe_retry_payment", limit=20, window_seconds=3600)

    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")
    if order.payment_method != "credit_card":
        raise HTTPException(status_code=400, detail="Only card payments can be retried")
    if order.payment_status != "failed":
        raise HTTPException(status_code=400, detail="Order is not in a failed payment state")
    failed_at = order.payment_failed_at
    if failed_at is None or (dt.datetime.utcnow() - failed_at).total_seconds() > RETRY_WINDOW_MINUTES * 60:
        raise HTTPException(status_code=410, detail="Payment retry window expired")
    if order.status != "new" or order.paid:
        raise HTTPException(status_code=400, detail="Order can no longer be paid")

    # Stripe availability is checked LAST (after every 4xx): without
    # STRIPE_SECRET_KEY this returns the same clean 501 as the
    # payment-intent endpoint.
    stripe = _stripe_client()
    if stripe is None:
        raise HTTPException(status_code=501, detail="card payments not configured")

    # Server-side total: the stored checkout total — never from the client.
    total = Decimal(str(order.total or 0))
    amount_cents = int(round(total * 100))
    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="Order total must be positive")

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            metadata={"order_id": str(order.id), "retry": "1"},
        )
    except Exception:  # Stripe API/network failure — never leak internals
        # The retry itself failed: re-arm the 30-minute window from now so
        # the customer can try again instead of being stuck.
        order.payment_status = "failed"
        order.payment_failed_at = dt.datetime.utcnow()
        db.add(
            models.OrderEvent(
                order_id=order.id,
                event_type="payment",
                message="Card payment retry failed — customer can retry for 30 more minutes",
                meta=json.dumps({"retry": True}),
            )
        )
        db.commit()
        raise HTTPException(status_code=502, detail="Could not create payment")
    # Fresh intent minted: clear the failure state; the webhook marks paid.
    order.payment_status = None
    order.payment_failed_at = None
    db.add(
        models.OrderEvent(
            order_id=order.id,
            event_type="payment",
            message="Card payment retry started — fresh PaymentIntent created",
            meta=json.dumps({"payment_intent": intent.id, "retry": True}),
        )
    )
    db.commit()
    return {
        "client_secret": intent.client_secret,
        "payment_intent_id": intent.id,
        "amount_cents": amount_cents,
        "currency": "usd",
    }
# === END FEATURE 10 ===
