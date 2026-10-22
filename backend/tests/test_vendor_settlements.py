"""Tests for the vendor settlement ledger foundation."""
import unittest
from decimal import Decimal

from app import models, schemas


class VendorSettlementSchemaTests(unittest.TestCase):
    def test_settlement_source_is_required_and_restricted(self):
        for source in ("admin_payout", "direct_customer_payment", "commission_collection"):
            payload = schemas.SettlementCreate(
                vendor_id=1, source=source, amount=Decimal("12.345"), method="zelle"
            )
            self.assertEqual(payload.source, source)
            self.assertEqual(payload.amount, Decimal("12.35"))

        with self.assertRaises(ValueError):
            schemas.SettlementCreate(vendor_id=1, source="customer_paid", amount=10)

    def test_settlement_method_is_restricted(self):
        payload = schemas.SettlementCreate(
            vendor_id=1, source="direct_customer_payment", amount=10, method="venmo"
        )
        self.assertEqual(payload.method, "venmo")
        with self.assertRaises(ValueError):
            schemas.SettlementCreate(
                vendor_id=1, source="admin_payout", amount=10, method="crypto"
            )

    def test_ledger_table_is_registered_for_create_all_migration(self):
        table = models.Base.metadata.tables["vendor_settlements"]
        self.assertIn("vendor_id", table.c)
        self.assertIn("order_id", table.c)
        self.assertIn("source", table.c)
        self.assertIn("amount", table.c)
        self.assertIn("method", table.c)


if __name__ == "__main__":
    unittest.main()
