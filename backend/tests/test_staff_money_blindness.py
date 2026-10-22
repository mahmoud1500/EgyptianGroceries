"""v48: staff money-blindness tests.

Owner decision: vendor/platform money figures are admin eyes only. Staff
keep full operational access, but on every staff-reachable route the money
fields must serialize as null while operational fields stay intact — and
admin responses must carry the full figures, unchanged.
"""
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.routers.admin import all_orders, all_vendors, admin_order_detail, stats

MONEY_KEYS = (
    "commission_rate",
    "gross",
    "commission",
    "paid",
    "owed",
    "collected_sales",
    "direct_sales",
    "direct_order_count",
    "direct_commission_due",
    "direct_commission_collected",
    "direct_commission_outstanding",
    "net_owed",
)


class StaffMoneyBlindnessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.admin = models.User(email="admin@t.test", hashed_password="x", name="Admin", role="admin")
        self.staff = models.User(email="staff@t.test", hashed_password="x", name="Staff", role="staff")
        self.owner = models.User(email="owner@t.test", hashed_password="x", name="Owner", role="vendor")
        self.customer = models.User(email="cust@t.test", hashed_password="x", name="Cust", role="customer")
        self.db.add_all([self.admin, self.staff, self.owner, self.customer])
        self.db.flush()
        self.vendor = models.Vendor(name="Blindness Kitchen", owner_id=self.owner.id)
        self.vendor.commission_rate = Decimal("10.00")
        self.db.add(self.vendor)
        self.db.flush()
        # One completed card order ($200, $20 commission snapshot) and one
        # completed cash order ($100, $10 snapshot): revenue 300, direct
        # outstanding 10, collected-side net 200 - 20 - 10 = 170.
        for method, total, due in (("credit_card", "200.00", "20.00"), ("cash", "100.00", "10.00")):
            self.db.add(models.Order(
                customer_id=self.customer.id,
                vendor_id=self.vendor.id,
                status="completed",
                fulfillment="pickup",
                payment_method=method,
                subtotal=Decimal(total),
                total=Decimal(total),
                commission_due=Decimal(due),
            ))
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    # --- /admin/vendors -------------------------------------------------
    def test_vendors_staff_gets_null_money_but_full_operations(self):
        rows = all_vendors(db=self.db, admin=self.staff)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for key in MONEY_KEYS:
            self.assertIsNone(row[key], f"staff must not see {key}")
        self.assertIsNone(row["revenue"])
        # Operational data stays.
        self.assertEqual(row["name"], "Blindness Kitchen")
        self.assertEqual(row["orders"], 2)
        self.assertEqual(row["owner_name"], "Owner")
        self.assertIn("is_paused", row)

    def test_vendors_admin_gets_full_money(self):
        rows = all_vendors(db=self.db, admin=self.admin)
        row = rows[0]
        self.assertEqual(row["commission_rate"], 10.0)
        self.assertEqual(row["revenue"], 300.00)
        self.assertEqual(row["collected_sales"], 200.00)
        self.assertEqual(row["commission"], 20.00)
        self.assertEqual(row["direct_sales"], 100.00)
        self.assertEqual(row["direct_commission_outstanding"], 10.00)
        self.assertEqual(row["net_owed"], 170.00)
        self.assertEqual(row["owed"], 170.00)

    # --- /admin/stats ---------------------------------------------------
    def test_stats_staff_gets_null_revenue_but_counts(self):
        s = stats(db=self.db, admin=self.staff)
        self.assertIsNone(s["revenue"])
        self.assertEqual(s["orders"], 2)
        self.assertEqual(s["vendors"], 1)
        self.assertEqual(s["customers"], 1)

    def test_stats_admin_gets_revenue(self):
        s = stats(db=self.db, admin=self.admin)
        self.assertEqual(s["revenue"], 300.00)

    # --- /admin/orders + detail -----------------------------------------
    def test_orders_staff_gets_null_commission_but_totals(self):
        orders = all_orders(status=None, vendor_id=None, db=self.db, admin=self.staff)
        self.assertEqual(len(orders), 2)
        for o in orders:
            self.assertIsNone(o.commission_due)
            self.assertGreater(float(o.total), 0)  # transactional total stays

    def test_orders_admin_gets_commission(self):
        orders = all_orders(status=None, vendor_id=None, db=self.db, admin=self.admin)
        dues = sorted(float(o.commission_due) for o in orders)
        self.assertEqual(dues, [10.00, 20.00])

    def test_order_detail_staff_null_commission_admin_full(self):
        order = self.db.query(models.Order).filter_by(payment_method="cash").one()
        det_staff = admin_order_detail(order.id, db=self.db, admin=self.staff)
        self.assertIsNone(det_staff["order"].commission_due)
        self.assertEqual(float(det_staff["order"].total), 100.00)
        det_admin = admin_order_detail(order.id, db=self.db, admin=self.admin)
        self.assertEqual(float(det_admin["order"].commission_due), 10.00)


if __name__ == "__main__":
    unittest.main()
