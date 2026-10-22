"""Unit tests for weekly direct-cash commission accounting."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect

from app import models
from app.commission import commission_due_for_order, commission_for_amount, effective_commission_rate


class CommissionReceivableTests(unittest.TestCase):
    def test_checkout_commission_rounds_to_cents(self):
        self.assertEqual(commission_for_amount(Decimal("100.00"), Decimal("15")), Decimal("15.00"))
        self.assertEqual(commission_for_amount(Decimal("12.37"), Decimal("12.5")), Decimal("1.55"))

    def test_vendor_rate_overrides_marketplace_default(self):
        vendor = SimpleNamespace(commission_rate=Decimal("15.00"))
        self.assertEqual(effective_commission_rate(vendor, Decimal("8")), Decimal("15.00"))

    def test_default_rate_used_when_vendor_rate_is_null(self):
        vendor = SimpleNamespace(commission_rate=None)
        self.assertEqual(effective_commission_rate(vendor, Decimal("8")), Decimal("8"))

    def test_saved_order_commission_snapshot_survives_rate_change(self):
        order = SimpleNamespace(commission_due=Decimal("15.00"), total=Decimal("100.00"), refunded_amount=0)
        vendor = SimpleNamespace(commission_rate=Decimal("25.00"))
        self.assertEqual(commission_due_for_order(order, vendor, Decimal("10")), Decimal("15.00"))

    def test_refund_reduces_commission_receivable_proportionally(self):
        order = SimpleNamespace(commission_due=Decimal("15.00"), total=Decimal("100.00"), refunded_amount=Decimal("20.00"))
        vendor = SimpleNamespace(commission_rate=Decimal("25.00"))
        self.assertEqual(commission_due_for_order(order, vendor, Decimal("10")), Decimal("12.00"))

    def test_legacy_order_without_snapshot_uses_configured_rate(self):
        order = SimpleNamespace(commission_due=None, total=Decimal("80.00"), refunded_amount=0)
        vendor = SimpleNamespace(commission_rate=None)
        self.assertEqual(commission_due_for_order(order, vendor, Decimal("10")), Decimal("8.00"))

    def test_new_order_column_is_migration_registered(self):
        self.assertIn("commission_due", models.Base.metadata.tables["orders"].c)
        engine = create_engine("sqlite:///:memory:")
        try:
            models.Base.metadata.create_all(bind=engine)
            self.assertIn("commission_due", {c["name"] for c in inspect(engine).get_columns("orders")})
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
