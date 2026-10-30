"""Admin financial dashboard and refund-ledger regression tests."""
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import models  # noqa: E402
from app.routers.admin import analytics, list_refunds  # noqa: E402


class AdminFinancialDashboardTests:
    def setup_method(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.admin = models.User(
            email="admin-finance@test.local",
            hashed_password="x",
            name="Finance Admin",
            role="admin",
        )
        self.customer = models.User(
            email="customer-finance@test.local",
            hashed_password="x",
            name="Finance Customer",
            role="customer",
        )
        self.owner = models.User(
            email="vendor-finance@test.local",
            hashed_password="x",
            name="Finance Vendor",
            role="vendor",
        )
        self.db.add_all([self.admin, self.customer, self.owner])
        self.db.flush()
        self.vendor = models.Vendor(name="Finance Kitchen", owner_id=self.owner.id)
        self.vendor.commission_rate = Decimal("10.00")
        self.db.add(self.vendor)
        self.db.flush()

    def teardown_method(self):
        self.db.close()
        self.engine.dispose()

    def _order(self, status, method, total, commission, refunded=0):
        order = models.Order(
            customer_id=self.customer.id,
            vendor_id=self.vendor.id,
            status=status,
            fulfillment="pickup",
            payment_method=method,
            subtotal=Decimal(str(total)),
            delivery_fee=Decimal("0.00"),
            tax=Decimal("0.00"),
            total=Decimal(str(total)),
            commission_due=Decimal(str(commission)),
            refunded_amount=Decimal(str(refunded)),
        )
        self.db.add(order)
        self.db.flush()
        return order

    def test_analytics_includes_commission_split_and_refunds(self):
        self._order("completed", "credit_card", "100.00", "10.00", "20.00")
        self._order("completed", "cash", "50.00", "5.00", "0.00")
        self._order("cancelled", "credit_card", "40.00", "0.00", "40.00")

        result = analytics(days=30, db=self.db, admin=self.admin)
        totals = result["totals"]

        assert totals["gross"] == 150.00
        assert totals["orders"] == 2
        assert totals["commission_earned"] == 13.00
        assert totals["platform_commission"] == 8.00
        assert totals["direct_commission_due"] == 5.00
        assert totals["refunds"] == 60.00
        assert totals["refunded_orders"] == 2

    def test_refund_ledger_classifies_status_and_reconciles_vendor_commission(self):
        order = self._order("completed", "credit_card", "100.00", "10.00", "20.00")
        events = [
            ("Admin Stripe refund issued: re_success", {
                "refund_id": "re_success", "amount": "20.00", "stripe_status": "succeeded"
            }),
            ("Admin Stripe refund NOT confirmed", {
                "refund_id": "re_pending", "amount": "5.00", "stripe_status": "pending"
            }),
            ("Admin Stripe refund FAILED", {
                "refund_id": "re_failed", "amount": "3.00", "stripe_status": "failed"
            }),
            ("Unmatched Stripe refund(s) require reconciliation", {
                "unmatched_refund_ids": ["re_external"], "payment_intent": "pi_external"
            }),
        ]
        for message, meta in events:
            self.db.add(models.OrderEvent(
                order_id=order.id,
                event_type="refund",
                message=message,
                meta=json.dumps(meta),
            ))
        self.db.flush()

        result = list_refunds(limit=100, db=self.db, admin=self.admin)
        summary = result["summary"]
        by_status = {item["status"]: item for item in result["items"]}

        assert summary["succeeded_count"] == 1
        assert summary["succeeded_amount"] == 20.00
        assert summary["pending_count"] == 1
        assert summary["pending_amount"] == 5.00
        assert summary["failed_count"] == 1
        assert summary["needs_review_count"] == 1
        assert by_status["succeeded"]["remaining_balance"] == 80.00
        assert by_status["succeeded"]["commission_after_refund"] == 8.00
        assert by_status["needs_review"]["unmatched_refund_ids"] == ["re_external"]
