"""Unit tests for weekly direct-payment commission accounting."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import models, schemas
from app.commission import (
    DIRECT_PAYMENT_METHODS,
    PLATFORM_PAYMENT_METHODS,
    commission_due_for_order,
    commission_for_amount,
    effective_commission_rate,
)
from app.routers.admin import (
    _commission_receivable_for_vendor,
    _vendor_money,
    create_settlement,
)
from app.routers.vendors import my_commission_receivables


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


class DirectPaymentReceivableTests(unittest.TestCase):
    """Integration tests (in-memory DB, real router helpers): completed
    cash/Zelle/Venmo orders create commission receivables; platform
    methods (card / Apple Pay / Google Pay) never do; the admin worklist,
    the vendor's own balance, and the reconciled money summary agree."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.admin = models.User(email="admin@t.test", hashed_password="x", name="Admin", role="admin")
        self.owner = models.User(email="owner@t.test", hashed_password="x", name="Owner", role="vendor")
        self.db.add_all([self.admin, self.owner])
        self.db.flush()
        self.vendor = models.Vendor(name="Mixed Methods Kitchen", owner_id=self.owner.id)
        self.vendor.commission_rate = Decimal("10.00")
        self.db.add(self.vendor)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _order(self, method, total, status="completed", snapshot=True):
        total = Decimal(str(total))
        order = models.Order(
            vendor_id=self.vendor.id,
            status=status,
            fulfillment="pickup",
            payment_method=method,
            subtotal=total,
            total=total,
            commission_due=(total * Decimal("0.10")) if snapshot else None,
        )
        self.db.add(order)
        self.db.flush()
        return order

    def _mixed_orders(self):
        self._order("cash", "100.00")
        self._order("zelle", "50.00")
        self._order("venmo", "50.00")
        self._order("credit_card", "200.00")
        self._order("apple_pay", "40.00")
        self._order("google_pay", "30.00")
        self._order("cash", "999.00", status="new")  # not completed: must not count

    def test_method_constants_partition_checkout_methods(self):
        self.assertEqual(
            set(DIRECT_PAYMENT_METHODS) | set(PLATFORM_PAYMENT_METHODS),
            set(schemas.PAYMENT_METHODS),
        )
        self.assertFalse(set(DIRECT_PAYMENT_METHODS) & set(PLATFORM_PAYMENT_METHODS))

    def test_direct_methods_create_receivables_platform_methods_do_not(self):
        self._mixed_orders()
        rec = _commission_receivable_for_vendor(self.db, self.vendor, Decimal("0"))
        self.assertEqual(rec["direct_order_count"], 3)
        self.assertEqual(rec["direct_sales"], 200.00)
        self.assertEqual(rec["commission_due"], 20.00)
        self.assertEqual(rec["commission_collected"], 0.00)
        self.assertEqual(rec["outstanding_commission"], 20.00)
        self.assertEqual(
            {o["payment_method"] for o in rec["orders"]}, {"cash", "zelle", "venmo"}
        )

    def test_vendor_mine_endpoint_agrees_with_admin(self):
        self._mixed_orders()
        admin_rec = _commission_receivable_for_vendor(self.db, self.vendor, Decimal("0"))
        mine = my_commission_receivables(self.db, self.owner)
        self.assertEqual(len(mine), 1)
        row = mine[0]
        self.assertEqual(row["vendor_id"], self.vendor.id)
        self.assertEqual(row["direct_order_count"], admin_rec["direct_order_count"])
        self.assertEqual(row["commission_due"], admin_rec["commission_due"])
        self.assertEqual(row["commission_collected"], admin_rec["commission_collected"])
        self.assertEqual(row["outstanding_commission"], admin_rec["outstanding_commission"])

    def test_case_insensitive_direct_method_match(self):
        self._order("Zelle", "50.00")
        self._order(" VENMO ", "50.00")
        rec = _commission_receivable_for_vendor(self.db, self.vendor, Decimal("0"))
        self.assertEqual(rec["direct_order_count"], 2)
        self.assertEqual(rec["commission_due"], 10.00)

    def _collect(self, amount):
        return create_settlement(
            schemas.SettlementCreate(
                vendor_id=self.vendor.id,
                source="commission_collection",
                amount=Decimal(str(amount)),
                method="zelle",
            ),
            self.db,
            self.admin,
        )

    def test_collection_reduces_outstanding_and_overcollection_is_guarded(self):
        self._mixed_orders()
        self._collect("12.00")
        rec = _commission_receivable_for_vendor(self.db, self.vendor, Decimal("0"))
        self.assertEqual(rec["commission_collected"], 12.00)
        self.assertEqual(rec["outstanding_commission"], 8.00)
        mine = my_commission_receivables(self.db, self.owner)
        self.assertEqual(mine[0]["outstanding_commission"], 8.00)
        money = _vendor_money(self.db, self.vendor, Decimal("0"))
        self.assertEqual(money["direct_commission_outstanding"], 8.00)
        with self.assertRaises(HTTPException) as ctx:
            self._collect("8.01")
        self.assertEqual(ctx.exception.status_code, 422)
        self._collect("8.00")
        rec = _commission_receivable_for_vendor(self.db, self.vendor, Decimal("0"))
        self.assertEqual(rec["outstanding_commission"], 0.00)

    def test_vendor_money_reconciles_collected_and_direct(self):
        self._mixed_orders()
        money = _vendor_money(self.db, self.vendor, Decimal("0"))
        # Platform side: (200 + 40 + 30) collected, 10% commission on it.
        self.assertEqual(money["collected_sales"], 270.00)
        self.assertEqual(money["commission"], 27.00)
        self.assertEqual(money["gross"], money["collected_sales"])  # legacy key
        # Direct side: $200 of direct sales, $20 commission outstanding.
        self.assertEqual(money["direct_sales"], 200.00)
        self.assertEqual(money["direct_commission_outstanding"], 20.00)
        # net = 270 − 27 − 0 payouts − 20 direct outstanding
        self.assertEqual(money["net_owed"], 223.00)
        self.assertEqual(money["owed"], money["net_owed"])  # legacy key
        # A payout recorded in the v40 VendorPayout ledger reduces the net.
        self.db.add(models.VendorPayout(vendor_id=self.vendor.id, amount=Decimal("100.00")))
        self.db.flush()
        money = _vendor_money(self.db, self.vendor, Decimal("0"))
        self.assertEqual(money["paid"], 100.00)
        self.assertEqual(money["net_owed"], 123.00)
        # A payout recorded as a settlement (source=admin_payout) counts too.
        create_settlement(
            schemas.SettlementCreate(
                vendor_id=self.vendor.id, source="admin_payout",
                amount=Decimal("50.00"), method="bank_transfer",
            ),
            self.db,
            self.admin,
        )
        money = _vendor_money(self.db, self.vendor, Decimal("0"))
        self.assertEqual(money["paid"], 150.00)
        self.assertEqual(money["net_owed"], 73.00)

    def test_net_owed_can_go_negative_for_direct_only_vendor(self):
        vendor2 = models.Vendor(name="Cash Only Kitchen", owner_id=self.owner.id)
        vendor2.commission_rate = Decimal("10.00")
        self.db.add(vendor2)
        self.db.flush()
        order = models.Order(
            vendor_id=vendor2.id, status="completed", fulfillment="pickup",
            payment_method="zelle", subtotal=Decimal("100.00"),
            total=Decimal("100.00"), commission_due=Decimal("10.00"),
        )
        self.db.add(order)
        self.db.flush()
        money = _vendor_money(self.db, vendor2, Decimal("0"))
        self.assertEqual(money["collected_sales"], 0.00)
        self.assertEqual(money["direct_commission_outstanding"], 10.00)
        self.assertEqual(money["net_owed"], -10.00)  # vendor owes the marketplace


if __name__ == "__main__":
    unittest.main()
