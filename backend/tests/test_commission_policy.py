"""Regression tests for the marketplace commission base."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from app.commission import commission_due_for_order, commissionable_food_amount


class CommissionPolicyTests(unittest.TestCase):
    def test_commissionable_amount_is_discounted_food_only(self):
        order = SimpleNamespace(
            subtotal=Decimal("100.00"),
            discount_amount=Decimal("10.00"),
            points_discount=Decimal("5.00"),
            tax=Decimal("8.50"),
            delivery_fee=Decimal("12.00"),
            total=Decimal("105.50"),
        )

        self.assertEqual(commissionable_food_amount(order), Decimal("85.00"))
        self.assertEqual(
            commission_due_for_order(
                SimpleNamespace(**{**vars(order), "commission_due": None, "refunded_amount": 0}),
                vendor=None,
                default_rate=Decimal("10"),
            ),
            Decimal("8.50"),
        )

    def test_legacy_missing_discount_fields_default_to_zero(self):
        order = SimpleNamespace(
            subtotal=Decimal("24.99"),
            total=Decimal("40.00"),
            commission_due=None,
            refunded_amount=0,
        )

        self.assertEqual(commissionable_food_amount(order), Decimal("24.99"))
        self.assertEqual(
            commission_due_for_order(order, vendor=None, default_rate=Decimal("10")),
            Decimal("2.50"),
        )

    def test_existing_commission_snapshot_is_preserved(self):
        order = SimpleNamespace(
            subtotal=Decimal("100.00"),
            discount_amount=Decimal("10.00"),
            points_discount=Decimal("5.00"),
            total=Decimal("120.00"),
            commission_due=Decimal("12.00"),
            refunded_amount=0,
        )

        self.assertEqual(
            commission_due_for_order(order, vendor=None, default_rate=Decimal("5")),
            Decimal("12.00"),
        )

    def test_discounts_cannot_make_commissionable_amount_negative(self):
        order = SimpleNamespace(
            subtotal=Decimal("10.00"),
            discount_amount=Decimal("8.00"),
            points_discount=Decimal("5.00"),
        )

        self.assertEqual(commissionable_food_amount(order), Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
