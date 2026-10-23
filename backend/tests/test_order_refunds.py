"""Regression tests for scoped Stripe cancellation refunds.

All Stripe calls are mocked; no live payment or refund is issued.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app.routers import orders as order_routes  # noqa: E402


class FakeDB:
    def __init__(self):
        self.events = []

    def add(self, value):
        self.events.append(value)


def test_payment_intent_resolves_direct_wallet_reference():
    db = SimpleNamespace(
        scalars=lambda query: iter([
            SimpleNamespace(meta='{"payment_intent":"pi_wallet123"}')
        ])
    )
    stripe = SimpleNamespace()
    result = order_routes._stripe_payment_intent_id(db, SimpleNamespace(id=1), stripe)
    assert result == "pi_wallet123"


def test_cancel_refund_is_scoped_to_remaining_suborder_amount(monkeypatch):
    db = FakeDB()
    refund_create = Mock(return_value={"id": "re_test123", "amount": 2500})
    stripe = SimpleNamespace(Refund=SimpleNamespace(create=refund_create))
    monkeypatch.setattr(order_routes, "_stripe_client", lambda: stripe)
    monkeypatch.setattr(order_routes, "_stripe_payment_intent_id", lambda *args: "pi_group123")
    monkeypatch.setattr(order_routes, "_successful_refund_total", lambda *args: Decimal("5.00"))
    order = SimpleNamespace(
        id=44, paid=True, payment_method="credit_card", total=Decimal("30.00"),
        refunded_amount=Decimal("5.00"),
    )

    order_routes._stripe_refund_on_cancel(db, order)

    refund_create.assert_called_once_with(
        payment_intent="pi_group123",
        amount=2500,
        idempotency_key="order-cancel-refund-44-2500",
    )
    assert order.refunded_amount == Decimal("30.00")
    refund_event = next(e for e in db.events if e.event_type == "refund")
    assert '"amount": "25.00"' in refund_event.meta
    assert "Stripe refund issued" in refund_event.message


def test_fully_refunded_order_does_not_call_stripe(monkeypatch):
    db = FakeDB()
    refund_create = Mock()
    stripe = SimpleNamespace(Refund=SimpleNamespace(create=refund_create))
    monkeypatch.setattr(order_routes, "_stripe_client", lambda: stripe)
    monkeypatch.setattr(order_routes, "_stripe_payment_intent_id", lambda *args: "pi_group123")
    monkeypatch.setattr(order_routes, "_successful_refund_total", lambda *args: Decimal("30.00"))
    order = SimpleNamespace(
        id=45, paid=True, payment_method="credit_card", total=Decimal("30.00"),
        refunded_amount=Decimal("30.00"),
    )

    order_routes._stripe_refund_on_cancel(db, order)

    refund_create.assert_not_called()
    assert any("already fully refunded" in e.message for e in db.events)
