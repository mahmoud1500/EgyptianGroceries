"""Regression tests for delivery cost confirmation and settlement gates."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from app.routers.delivery import (
    _delivery_update_error,
    _recalculate_subsidy,
    _serialize,
)


def job(**overrides):
    values = {
        "id": 7,
        "order_id": 12,
        "mode": "third_party",
        "provider": "manual",
        "provider_reference": None,
        "status": "picked_up",
        "quoted_cost": Decimal("9.00"),
        "actual_cost": Decimal("0.00"),
        "actual_cost_confirmed": False,
        "customer_fee": Decimal("4.00"),
        "platform_subsidy": Decimal("0.00"),
        "payment_status": "unpaid",
        "notes": None,
        "created_at": None,
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class DeliveryCostControlTests(unittest.TestCase):
    def test_unknown_actual_cost_is_not_reported_as_zero(self):
        delivery = job()
        _recalculate_subsidy(delivery)
        payload = _serialize(delivery)

        self.assertFalse(payload["actual_cost_confirmed"])
        self.assertIsNone(payload["actual_cost"])
        self.assertIsNone(payload["platform_subsidy"])

    def test_confirmed_zero_cost_is_distinct_from_unknown(self):
        delivery = job(actual_cost_confirmed=True, actual_cost=Decimal("0.00"))
        _recalculate_subsidy(delivery)
        payload = _serialize(delivery)

        self.assertTrue(payload["actual_cost_confirmed"])
        self.assertEqual(payload["actual_cost"], "0.00")
        self.assertEqual(payload["platform_subsidy"], "0.00")

    def test_delivery_cannot_be_completed_without_confirmed_cost(self):
        delivery = job()
        self.assertIn(
            "Record the actual delivery cost",
            _delivery_update_error(delivery, {"status": "delivered"}),
        )

    def test_explicit_zero_cost_is_valid_delivery_evidence(self):
        delivery = job()
        self.assertIsNone(
            _delivery_update_error(
                delivery,
                {"status": "delivered", "actual_cost": Decimal("0.00")},
            )
        )

    def test_courier_payment_requires_delivered_job_and_confirmed_cost(self):
        delivery = job(actual_cost_confirmed=True, actual_cost=Decimal("9.00"))
        self.assertIn(
            "only be marked paid after delivery",
            _delivery_update_error(delivery, {"payment_status": "paid"}),
        )
        delivery.status = "delivered"
        self.assertIsNone(
            _delivery_update_error(delivery, {"payment_status": "paid"})
        )


if __name__ == "__main__":
    unittest.main()
