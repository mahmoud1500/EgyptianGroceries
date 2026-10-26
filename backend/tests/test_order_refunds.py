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

    def scalars(self, query):
        return iter(self.events)


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
    refund_create = Mock(return_value={"id": "re_test123", "amount": 2500, "status": "succeeded"})
    stripe = SimpleNamespace(Refund=SimpleNamespace(
        create=refund_create,
        list=Mock(return_value={"data": [], "has_more": False}),
    ))
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
    stripe = SimpleNamespace(Refund=SimpleNamespace(
        create=refund_create,
        list=Mock(return_value={"data": [], "has_more": False}),
    ))
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


def test_cancel_refund_blocks_unmatched_dashboard_refund(monkeypatch):
    db = FakeDB()
    refund_create = Mock()
    stripe = SimpleNamespace(Refund=SimpleNamespace(
        create=refund_create,
        list=Mock(return_value={"data": [{"id": "re_dashboard", "status": "succeeded"}], "has_more": False}),
    ))
    monkeypatch.setattr(order_routes, "_stripe_client", lambda: stripe)
    monkeypatch.setattr(order_routes, "_stripe_payment_intent_id", lambda *args: "pi_group123")
    order = SimpleNamespace(
        id=46, paid=True, payment_method="credit_card", total=Decimal("30.00"),
        refunded_amount=Decimal("0.00"),
    )

    order_routes._stripe_refund_on_cancel(db, order)

    refund_create.assert_not_called()
    assert any("unmatched Stripe refund" in e.message for e in db.events)
    assert any("re_dashboard" in e.meta for e in db.events)


def test_cancel_refund_fails_closed_when_stripe_reconciliation_unavailable(monkeypatch):
    db = FakeDB()
    refund_create = Mock()
    refund_list = Mock(side_effect=RuntimeError("Stripe unavailable"))
    stripe = SimpleNamespace(Refund=SimpleNamespace(create=refund_create, list=refund_list))
    monkeypatch.setattr(order_routes, "_stripe_client", lambda: stripe)
    monkeypatch.setattr(order_routes, "_stripe_payment_intent_id", lambda *args: "pi_group123")
    order = SimpleNamespace(
        id=47, paid=True, payment_method="credit_card", total=Decimal("30.00"),
        refunded_amount=Decimal("0.00"),
    )

    order_routes._stripe_refund_on_cancel(db, order)

    refund_create.assert_not_called()
    assert any("reconciliation unavailable" in e.message for e in db.events)


def test_cancel_refund_blocks_when_stripe_refund_list_is_paginated(monkeypatch):
    db = FakeDB()
    refund_create = Mock()
    stripe = SimpleNamespace(Refund=SimpleNamespace(
        create=refund_create,
        list=Mock(return_value={"data": [], "has_more": True}),
    ))
    monkeypatch.setattr(order_routes, "_stripe_client", lambda: stripe)
    monkeypatch.setattr(order_routes, "_stripe_payment_intent_id", lambda *args: "pi_group123")
    order = SimpleNamespace(
        id=48, paid=True, payment_method="credit_card", total=Decimal("30.00"),
        refunded_amount=Decimal("0.00"),
    )

    order_routes._stripe_refund_on_cancel(db, order)

    refund_create.assert_not_called()
    assert any("reconciliation unavailable" in e.message for e in db.events)



def test_successful_refund_total_ignores_pending_and_failed_statuses():
    db = FakeDB()
    db.events = [
        SimpleNamespace(message="Stripe refund issued", meta='{"amount":"10.00","stripe_status":"succeeded"}'),
        SimpleNamespace(message="Refund pending", meta='{"amount":"5.00","stripe_status":"pending"}'),
        SimpleNamespace(message="Refund failed", meta='{"amount":"7.00","stripe_status":"failed"}'),
        SimpleNamespace(message="Legacy refund issued", meta='{"amount":"2.00"}'),
    ]
    assert order_routes._successful_refund_total(db, 1) == Decimal("12.00")


def test_known_pending_stripe_refund_still_blocks_new_refund():
    db = FakeDB()
    db.events = [
        SimpleNamespace(event_type="refund", meta='{"refund_id":"re_pending","amount":"5.00","stripe_status":"pending"}')
    ]
    stripe = SimpleNamespace(Refund=SimpleNamespace(
        list=Mock(return_value={"data":[{"id":"re_pending","status":"pending"}],"has_more":False})
    ))
    try:
        order_routes._unmatched_stripe_refunds(db, stripe, "pi_group123")
    except RuntimeError as exc:
        assert "unresolved status" in str(exc)
    else:
        raise AssertionError("pending refund must block additional refunds")


def test_unknown_stripe_refund_status_blocks_new_refund():
    db = FakeDB()
    stripe = SimpleNamespace(Refund=SimpleNamespace(
        list=Mock(return_value={"data":[{"id":"re_unknown","status":"processing"}],"has_more":False})
    ))
    try:
        order_routes._unmatched_stripe_refunds(db, stripe, "pi_group123")
    except RuntimeError as exc:
        assert "unrecognized status" in str(exc)
    else:
        raise AssertionError("unknown status must block additional refunds")


def test_cancel_pending_stripe_refund_is_not_counted_as_refunded(monkeypatch):
    db = FakeDB()
    stripe = SimpleNamespace(Refund=SimpleNamespace(
        create=Mock(return_value={"id":"re_pending","amount":1000,"status":"pending"}),
        list=Mock(return_value={"data":[],"has_more":False}),
    ))
    monkeypatch.setattr(order_routes, "_stripe_client", lambda: stripe)
    monkeypatch.setattr(order_routes, "_stripe_payment_intent_id", lambda *args: "pi_group123")
    monkeypatch.setattr(order_routes, "_successful_refund_total", lambda *args: Decimal("0"))
    order = SimpleNamespace(id=49, paid=True, payment_method="credit_card",
                            total=Decimal("10.00"), refunded_amount=Decimal("0.00"))
    order_routes._stripe_refund_on_cancel(db, order)
    assert order.refunded_amount == Decimal("0.00")
    event = next(e for e in db.events if "NOT confirmed" in e.message)
    assert '"stripe_status": "pending"' in event.meta
