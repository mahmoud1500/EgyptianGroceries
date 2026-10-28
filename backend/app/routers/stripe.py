"""Stripe Checkout integration.

Card payments are optional: without STRIPE_SECRET_KEY card checkout is
disabled before an order is created.
The secret key is read from the environment at request time and is never
logged or returned in a response.
"""
import datetime as dt  # === FEATURE 10: payment-failure timestamps ===
import json
import os
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import auth, emailer, models
from ..database import get_db
from ..ratelimit import check_rate_limit

router = APIRouter(prefix="/api/stripe", tags=["stripe"])


def _send_paid_order_receipts(db: Session, orders: list[models.Order]) -> None:
    """Best-effort, idempotent receipt email after payment is committed."""
    for order in orders:
        if order is None or not order.paid:
            continue
        already_sent = db.query(models.OrderEvent.id).filter(
            models.OrderEvent.order_id == order.id,
            models.OrderEvent.event_type == "receipt",
        ).first()
        if already_sent:
            continue
        try:
            sent = emailer.send_payment_receipt(order)
            if sent:
                db.add(models.OrderEvent(
                    order_id=order.id,
                    event_type="receipt",
                    message="Payment receipt emailed to customer",
                    meta=json.dumps({"to": order.customer.email if order.customer else ""}),
                ))
                db.commit()
        except Exception as exc:
            db.rollback()
            print(f"[stripe] receipt email failed for order #{order.id}: {exc}")



class CheckoutSessionIn(BaseModel):
    order_id: int


class CheckoutGroupSessionIn(BaseModel):
    checkout_group: str


class PaymentIntentIn(BaseModel):
    order_id: int


def _stripe_client():
    """Return the configured stripe module, or None when card payments are
    not configured (no STRIPE_SECRET_KEY) or the package is unavailable."""
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        return None
    try:
        import stripe
    except ImportError:
        return None
    stripe.api_key = key
    return stripe


def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "http://localhost:8000").rstrip("/")


def _to_cents(value) -> int:
    return int(round(Decimal(str(value)) * 100))


def _checkout_amounts(stripe, orders):
    """Build Stripe line items and discounts so Checkout equals stored order totals."""
    line_items = []
    gross = Decimal("0")
    tax_total = Decimal("0")
    for order in orders:
        for item in order.items:
            unit = Decimal(str(item.unit_price))
            line_items.append({
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"{item.dish_name} ({order.vendor.name})"},
                    "unit_amount": _to_cents(unit),
                },
                "quantity": item.quantity,
            })
            gross += unit * item.quantity
        fee = Decimal(str(order.delivery_fee or 0))
        if fee > 0:
            line_items.append({
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Delivery fee ({order.vendor.name})"},
                    "unit_amount": _to_cents(fee),
                },
                "quantity": 1,
            })
            gross += fee
        tax_total += Decimal(str(order.tax or 0))
    if not line_items:
        raise HTTPException(status_code=400, detail="Order has no items")
    if tax_total > 0:
        tax_cents = _to_cents(tax_total)
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Sales tax"},
                "unit_amount": tax_cents,
            },
            "quantity": 1,
        })
        gross += Decimal(tax_cents) / 100

    stored_total = sum((Decimal(str(order.total or 0)) for order in orders), Decimal("0"))
    gross_cents = _to_cents(gross)
    total_cents = _to_cents(stored_total)
    discount_cents = gross_cents - total_cents
    if total_cents <= 0:
        raise HTTPException(status_code=400, detail="Card payment is not needed for a zero-total order")
    if discount_cents < 0 or discount_cents >= gross_cents:
        raise HTTPException(status_code=400, detail="Order total could not be prepared for card payment")

    discounts = []
    if discount_cents:
        coupon = stripe.Coupon.create(
            amount_off=discount_cents,
            currency="usd",
            duration="once",
            name="Order discounts",
        )
        discounts.append({"coupon": coupon.id})
    return line_items, discounts


@router.get("/status")
def stripe_status(request: Request):
    """Public: is card payment actually configured? The customer checkout
    calls this once to label the credit-card option honestly. No auth
    needed — it only reveals whether the key is set, never the key itself."""
    check_rate_limit(request, "stripe_status", limit=120, window_seconds=3600)
    return {"card_payments_enabled": _stripe_client() is not None}


# === FEATURE 10: payment-failure hook ===
def _record_payment_failure(db: Session, order: models.Order) -> None:
    """Mark an order's card payment as failed so the customer can retry it
    within 30 minutes (POST /api/orders/{id}/retry-payment).

    Called wherever the Stripe payment-intent / checkout-session flow errors
    out. Never raises: the 502 response must still go out even if the
    bookkeeping write fails.
    """
    try:
        order.payment_status = "failed"
        order.payment_failed_at = dt.datetime.utcnow()
        db.add(
            models.OrderEvent(
                order_id=order.id,
                event_type="payment",
                message="Card payment failed — customer can retry for 30 minutes",
                meta=json.dumps({"payment_status": "failed"}),
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"[stripe] failed to record payment failure: {exc}")
# === END FEATURE 10 ===


# === v41: card brand/last4 enrichment (Oct 2026). Only the brand (e.g.
# "visa") and the last 4 digits are ever recorded — NEVER the raw card
# number, expiry date, or CVC. Stripe's hosted checkout / PaymentSheet keeps
# the full card data; this server only ever sees brand + last4 from
# Stripe's API. All enrichment is best-effort: the paid marking must never
# fail because of it. ===
def _g(obj, key):
    """Get a value from a StripeObject or plain dict."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:  # noqa: BLE001
            return None
    return getattr(obj, key, None)


def _card_from_payment_method(stripe, pm):
    """(brand, last4) from a payment method (object or id). (None, None)
    on any failure."""
    try:
        if isinstance(pm, str):
            pm = stripe.PaymentMethod.retrieve(pm)
        card = _g(pm, "card")
        if not card:
            return None, None
        return _g(card, "brand"), _g(card, "last4")
    except Exception:  # noqa: BLE001 — best-effort
        return None, None


def _card_from_checkout_session(stripe, session_id):
    """(brand, last4) for a Checkout Session. (None, None) on any failure."""
    try:
        if not session_id:
            return None, None
        s = stripe.checkout.Session.retrieve(
            session_id, expand=["payment_intent.payment_method"]
        )
        pi = _g(s, "payment_intent")
        if isinstance(pi, str):
            pi = stripe.PaymentIntent.retrieve(pi, expand=["payment_method"])
        return _card_from_payment_method(stripe, _g(pi, "payment_method"))
    except Exception:  # noqa: BLE001 — best-effort
        return None, None


def _card_from_payment_intent(stripe, pi_id):
    """(brand, last4) for a PaymentIntent id. (None, None) on any failure."""
    try:
        if not pi_id:
            return None, None
        pi = stripe.PaymentIntent.retrieve(pi_id, expand=["payment_method"])
        return _card_from_payment_method(stripe, _g(pi, "payment_method"))
    except Exception:  # noqa: BLE001 — best-effort
        return None, None


def _store_card_details(stripe_client, db, orders, brand, last4):
    """Best-effort: stamp brand/last4 on paid orders, then commit. Never
    raises — the paid marking already committed, and card metadata must
    never break it (a failure here must NOT make Stripe retry)."""
    if stripe_client is None or not (brand or last4):
        return
    try:
        brand = (str(brand)[:20] if brand else None) or None
        last4 = (str(last4)[:4] if last4 else None) or None
        for order in orders or []:
            if order is None:
                continue
            order.card_brand = brand
            order.card_last4 = last4
        db.commit()
    except Exception as exc:  # noqa: BLE001 — enrichment is optional
        db.rollback()
        print(f"[stripe] card detail enrichment failed: {exc}")
# === END v41 card enrichment ===


@router.post("/checkout-session")
def create_checkout_session(
    payload: CheckoutSessionIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    check_rate_limit(request, "stripe_checkout_session", limit=20, window_seconds=3600)
    stripe = _stripe_client()
    if stripe is None:
        raise HTTPException(status_code=501, detail="card payments not configured")

    order = db.get(models.Order, payload.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")
    if order.payment_method != "credit_card":
        raise HTTPException(status_code=400, detail="This order was not placed for card payment")
    if order.status != "new":
        raise HTTPException(status_code=400, detail="Only new orders can be paid")
    if order.paid:
        raise HTTPException(status_code=400, detail="Order is already paid")

    base = _frontend_url()
    try:
        line_items, discounts = _checkout_amounts(stripe, [order])
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=line_items,
            discounts=discounts,
            metadata={"order_id": str(order.id)},
            success_url=f"{base}/orders/{order.id}/paid?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/orders/{order.id}",
        )
    except HTTPException:
        raise
    except Exception as e:  # Stripe API/network failure — never leak internals
        _record_payment_failure(db, order)  # === FEATURE 10 ===
        raise HTTPException(status_code=502, detail="Could not start card payment")
    return {"checkout_url": session.url}


@router.post("/checkout-group-session")
def create_checkout_group_session(
    payload: CheckoutGroupSessionIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(auth.get_optional_user),
):
    """ONE Stripe payment for a whole multi-vendor checkout.

    Builds the session from server-stored order totals, including tax and
    discounts. Guest groups are paid using their unguessable checkout UUID.
    """
    check_rate_limit(request, "stripe_checkout_group_session", limit=20, window_seconds=3600)
    from sqlalchemy import select

    stripe = _stripe_client()
    if stripe is None:
        raise HTTPException(status_code=501, detail="card payments not configured")

    orders = list(
        db.scalars(
            select(models.Order).where(models.Order.checkout_group == payload.checkout_group)
        ).all()
    )
    if not orders:
        raise HTTPException(status_code=404, detail="Checkout group not found")
    for order in orders:
        if order.payment_method != "credit_card":
            raise HTTPException(status_code=400, detail="This order was not placed for card payment")
        if order.customer_id is not None and (user is None or order.customer_id != user.id):
            raise HTTPException(status_code=403, detail="Not your order")
        if order.customer_id is None and user is not None:
            raise HTTPException(status_code=403, detail="Not your order")
        if order.status != "new":
            raise HTTPException(status_code=400, detail="Only new orders can be paid")
        if order.paid:
            raise HTTPException(status_code=400, detail="Order is already paid")

    # One combined session: line items from every sub-order's stored items,
    # plus each sub-order's delivery fee.
    base = _frontend_url()
    if user is None:
        success_url = f"{base}/payment-complete?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base}/"
    else:
        success_url = f"{base}/orders?paid=1"
        cancel_url = f"{base}/orders"
    try:
        line_items, discounts = _checkout_amounts(stripe, orders)
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=line_items,
            discounts=discounts,
            metadata={"checkout_group": payload.checkout_group},
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except HTTPException:
        raise
    except Exception:  # Stripe API/network failure — never leak internals
        for order in orders:
            _record_payment_failure(db, order)  # === FEATURE 10 ===
        raise HTTPException(status_code=502, detail="Could not start card payment")
    return {"checkout_url": session.url}


@router.post("/payment-intent")
def create_payment_intent(
    payload: PaymentIntentIn,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """PaymentIntent for the mobile app's Apple Pay / Google Pay sheet.

    The amount is computed SERVER-SIDE from the order's stored total (set at
    checkout from its items — a client-sent amount is never trusted).
    Works with Stripe TEST keys: the secret is read from STRIPE_SECRET_KEY at
    request time, like every other endpoint here. Without a key this returns
    501 and the app falls back to the other payment methods.
    """
    check_rate_limit(request, "stripe_payment_intent", limit=20, window_seconds=3600)
    stripe = _stripe_client()
    if stripe is None:
        raise HTTPException(status_code=501, detail="card payments not configured")

    order = db.get(models.Order, payload.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your order")
    if order.payment_method != "credit_card":
        raise HTTPException(status_code=400, detail="This order was not placed for card payment")
    if order.status != "new":
        raise HTTPException(status_code=400, detail="Only new orders can be paid")
    if order.paid:
        raise HTTPException(status_code=400, detail="Order is already paid")

    # Server-side total: the stored checkout total (subtotal - discounts +
    # delivery + tax). Never from the client.
    total = Decimal(str(order.total or 0))
    amount_cents = int(round(total * 100))
    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="Order total must be positive")

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            metadata={"order_id": str(order.id)},
        )
    except Exception:  # Stripe API/network failure — never leak internals
        _record_payment_failure(db, order)  # === FEATURE 10 ===
        raise HTTPException(status_code=502, detail="Could not create payment")
    return {
        "client_secret": intent.client_secret,
        "payment_intent_id": intent.id,
        "amount_cents": amount_cents,
        "currency": "usd",
    }


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=400, detail="webhook not configured")
    try:
        import stripe
    except ImportError:
        raise HTTPException(status_code=500, detail="stripe package not installed")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        stripe_session = event["data"]["object"]
        # stripe-python >= 8 returns StripeObject, not plain dicts.
        sess = stripe_session.to_dict() if hasattr(stripe_session, "to_dict") else stripe_session
        if sess.get("payment_status") != "paid":
            return {"received": True}
        meta = sess.get("metadata") or {}
        group = meta.get("checkout_group")
        if group:
            # Multi-vendor checkout: mark EVERY sub-order paid with the
            # same Stripe session reference.
            from sqlalchemy import select as _select

            try:
                orders = list(
                    db.scalars(
                        _select(models.Order).where(models.Order.checkout_group == group)
                    ).all()
                )
                for order in orders:
                    if order is not None and not order.paid:
                        order.paid = True
                        db.add(
                            models.OrderEvent(
                                order_id=order.id,
                                event_type="payment",
                                message="Payment received via Stripe (test)",
                                meta=json.dumps(
                                    {"stripe_session": sess.get("id"), "checkout_group": group}
                                ),
                            )
                        )
                db.commit()
            except Exception:
                db.rollback()
                # Return 500 so Stripe retries the delivery.
                raise HTTPException(status_code=500, detail="Failed to record payment")
            # v41: best-effort card brand/last4 on each paid sub-order (brand
            # + last4 ONLY — never raw PAN/expiry/CVC). The paid marking
            # already committed above; this must never fail it.
            _sc = _stripe_client()
            if _sc is not None:
                _store_card_details(
                    _sc, db, orders,
                    *_card_from_checkout_session(_sc, sess.get("id")),
                )
            _send_paid_order_receipts(db, orders)
            return {"received": True}
        order_id = meta.get("order_id")
        try:
            order_id = int(order_id)
        except (TypeError, ValueError):
            return {"received": True}
        try:
            order = db.get(models.Order, order_id)
            if order is not None and not order.paid:
                order.paid = True
                db.add(
                    models.OrderEvent(
                        order_id=order.id,
                        event_type="payment",
                        message="Payment received via Stripe (test)",
                        meta=json.dumps({"stripe_session": sess.get("id")}),
                    )
                )
                db.commit()
        except Exception:
            db.rollback()
            # Return 500 so Stripe retries the delivery.
            raise HTTPException(status_code=500, detail="Failed to record payment")
        # v41: best-effort card brand/last4 (see group branch above).
        _sc = _stripe_client()
        if _sc is not None and order is not None:
            _store_card_details(
                _sc, db, [order],
                *_card_from_checkout_session(_sc, sess.get("id")),
            )
        if order is not None:
            _send_paid_order_receipts(db, [order])

    if event["type"] == "payment_intent.succeeded":
        # Mobile wallet flow (Apple Pay / Google Pay via PaymentSheet).
        pi = event["data"]["object"]
        pi = pi.to_dict() if hasattr(pi, "to_dict") else pi
        meta = pi.get("metadata") or {}
        try:
            order_id = int(meta.get("order_id"))
        except (TypeError, ValueError):
            return {"received": True}
        try:
            order = db.get(models.Order, order_id)
            if order is not None and not order.paid:
                order.paid = True
                db.add(
                    models.OrderEvent(
                        order_id=order.id,
                        event_type="payment",
                        message="Payment received via Stripe PaymentIntent (test)",
                        meta=json.dumps({"payment_intent": pi.get("id")}),
                    )
                )
                db.commit()
        except Exception:
            db.rollback()
            # Return 500 so Stripe retries the delivery.
            raise HTTPException(status_code=500, detail="Failed to record payment")
        # v41: best-effort card brand/last4 from the PaymentIntent's method.
        _sc = _stripe_client()
        if _sc is not None and order is not None:
            _store_card_details(
                _sc, db, [order],
                *_card_from_payment_intent(_sc, pi.get("id")),
            )
        if order is not None:
            _send_paid_order_receipts(db, [order])
    return {"received": True}
