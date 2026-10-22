"""v48 commission-cycle coverage: the weekly statement state machine
(remind -> pause -> restore), idempotency, the blank-limit rule,
immediate restore on collection, scheduler guards, paused-checkout
enforcement on all three create paths, endpoint role guards, and
vendor statement scoping.

State machine under test (commission_cycle.run_weekly_statements):
  one statement per vendor per ISO week; when a pause limit is set and
  a vendor's outstanding commission is over it, week 1 reminds, week 2
  (same episode, still over) pauses direct payments; at or under the
  limit the episode closes and a pause is lifted. The warning is LIVE
  state (Vendor.commission_warned): a collection recorded by the admin
  re-evaluates and restores immediately, and settling an episode means
  the NEXT episode of debt starts with its own fresh warning week.

Run with:
    python -m unittest backend.tests.test_commission_cycle
"""
import asyncio
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

# The weekly scheduler must never start under tests (main.py guard).
os.environ.setdefault("DISABLE_CYCLE_SCHEDULER", "1")

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import auth, commission_cycle, emailer, models, schemas  # noqa: E402
from app import database as database_module  # noqa: E402
from app.routers import admin as admin_router  # noqa: E402
from app.routers import orders as orders_router  # noqa: E402
from app.routers import vendors as vendors_router  # noqa: E402

# Mondays (market time) three weeks apart.
MON_W1 = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
MON_W2 = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
MON_W3 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _request():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


class CycleBase(unittest.TestCase):
    def setUp(self):
        self.Session = _make_session()
        self.db = self.Session()
        self.owner = models.User(
            email="owner@example.com", hashed_password="x", role="vendor",
            name="Cycle Owner",
        )
        self.db.add(self.owner)
        self.db.flush()
        # 10% commission; open_time == close_time makes the pickup-time
        # validator treat the shop as always within hours, so checkout
        # tests pass regardless of when they run.
        self.vendor = models.Vendor(
            owner_id=self.owner.id, name="Cycle Kitchen",
            commission_rate=Decimal("10"),
            open_time="00:00", close_time="00:00",
        )
        self.db.add(self.vendor)
        self.db.flush()
        self.customer = models.User(
            email="buyer@example.com", hashed_password="x", role="customer",
        )
        self.admin = models.User(
            email="boss@example.com", hashed_password="x", role="admin",
        )
        self.staff = models.User(
            email="clerk@example.com", hashed_password="x", role="staff",
        )
        self.db.add_all([self.customer, self.admin, self.staff])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    # -- fixtures ------------------------------------------------------
    def set_limit(self, raw):
        """raw: a string like '10', or None to leave the Setting unset."""
        if raw is None:
            return
        row = self.db.get(models.Setting, "commission_pause_limit")
        if row is None:
            self.db.add(models.Setting(key="commission_pause_limit", value=raw))
        else:
            row.value = raw
        self.db.commit()

    def add_direct_order(self, total="200.00", method="zelle"):
        """A completed direct-pay order with the 10% snapshot locked in:
        $200 of sales -> $20 of commission due."""
        order = models.Order(
            customer_id=self.customer.id, vendor_id=self.vendor.id,
            status="completed", fulfillment="pickup", payment_method=method,
            subtotal=Decimal(total), total=Decimal(total),
            commission_due=Decimal(total) * Decimal("0.10"),
        )
        self.db.add(order)
        self.db.commit()
        return order

    def collect(self, amount):
        self.db.add(models.VendorSettlement(
            vendor_id=self.vendor.id, source="commission_collection",
            amount=Decimal(amount), method="cash",
        ))
        self.db.commit()

    def statements(self):
        return list(self.db.scalars(
            select(models.CommissionStatement)
            .where(models.CommissionStatement.vendor_id == self.vendor.id)
            .order_by(models.CommissionStatement.period_start)
        ))

    def paused(self):
        self.db.expire_all()
        return bool(self.db.get(models.Vendor, self.vendor.id).direct_pay_paused)

    def warned(self):
        self.db.expire_all()
        return bool(self.db.get(models.Vendor, self.vendor.id).commission_warned)


class StatementStateMachineTests(CycleBase):
    def test_week_key_is_iso_monday_to_sunday(self):
        key, start, end = commission_cycle.week_key_and_period(MON_W1)
        self.assertRegex(key, r"^\d{4}-W\d{2}$")
        self.assertEqual(start.isoformat(), "2026-10-19")
        self.assertEqual(end.isoformat(), "2026-10-25")
        key2, _, _ = commission_cycle.week_key_and_period(MON_W2)
        self.assertNotEqual(key, key2)

    def test_under_limit_no_remind_no_pause(self):
        self.set_limit("100")
        self.add_direct_order()  # $20 due, under the $100 limit
        summary = commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        self.assertEqual(summary["statements_created"], 1)
        self.assertEqual(summary["reminded"], [])
        self.assertEqual(summary["paused"], [])
        stmt = self.statements()[0]
        self.assertEqual(stmt.direct_sales, Decimal("200"))
        self.assertEqual(stmt.commission_due, Decimal("20"))
        self.assertEqual(stmt.commission_collected, Decimal("0"))
        self.assertEqual(stmt.outstanding, Decimal("20"))
        self.assertFalse(stmt.reminded)
        self.assertFalse(stmt.pause_applied)
        self.assertFalse(self.paused())

    def test_over_limit_reminds_week1_pauses_week2(self):
        self.set_limit("10")
        self.add_direct_order()  # $20 due > $10 limit
        s1 = commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        self.assertEqual(s1["reminded"], [self.vendor.id])
        self.assertEqual(s1["paused"], [])
        self.assertTrue(self.statements()[0].reminded)
        self.assertTrue(self.warned())  # live episode flag set by the warning
        self.assertFalse(self.paused())

        s2 = commission_cycle.run_weekly_statements(self.db, MON_W2, notify=False)
        self.assertEqual(s2["paused"], [self.vendor.id])
        self.assertEqual(s2["reminded"], [])
        self.assertTrue(self.statements()[1].pause_applied)
        self.assertTrue(self.paused())

    def test_idempotent_within_a_week(self):
        self.set_limit("10")
        self.add_direct_order()
        commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        again = commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        self.assertEqual(again["statements_created"], 0)
        self.assertEqual(again["reminded"], [])
        self.assertEqual(again["paused"], [])
        self.assertEqual(again["unpaused"], [])
        self.assertEqual(len(self.statements()), 1)

    def test_blank_limit_never_pauses(self):
        self.set_limit(None)  # Setting row never written at all
        self.add_direct_order()
        commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        commission_cycle.run_weekly_statements(self.db, MON_W2, notify=False)
        self.assertEqual(len(self.statements()), 2)
        self.assertTrue(all(not s.reminded for s in self.statements()))
        self.assertFalse(self.paused())
        # An explicit "0" behaves the same as blank.
        self.set_limit("0")
        commission_cycle.run_weekly_statements(self.db, MON_W3, notify=False)
        self.assertFalse(self.paused())

    def test_settle_under_limit_restores_on_next_run(self):
        self.set_limit("10")
        self.add_direct_order()
        commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        commission_cycle.run_weekly_statements(self.db, MON_W2, notify=False)
        self.assertTrue(self.paused())
        self.collect("15.00")  # outstanding $20 -> $5, back under the limit
        s3 = commission_cycle.run_weekly_statements(self.db, MON_W3, notify=False)
        self.assertEqual(s3["unpaused"], [self.vendor.id])
        self.assertFalse(self.paused())
        self.assertEqual(self.statements()[2].outstanding, Decimal("5"))

    def test_remind_and_pause_emails_sent(self):
        self.set_limit("10")
        self.add_direct_order()
        sent = []
        original = emailer.send_commission_statement_notice
        emailer.send_commission_statement_notice = (
            lambda to, name, **kw: sent.append((to, kw)) or True
        )
        try:
            commission_cycle.run_weekly_statements(self.db, MON_W1)
            commission_cycle.run_weekly_statements(self.db, MON_W2)
        finally:
            emailer.send_commission_statement_notice = original
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0][0], "owner@example.com")
        self.assertEqual(sent[0][1]["kind"], "reminded")
        self.assertEqual(sent[1][1]["kind"], "paused")
        self.assertEqual(sent[1][1]["outstanding"], "20.00")


class SettlementRestoreTests(CycleBase):
    def test_collection_restores_immediately(self):
        self.set_limit("10")
        self.add_direct_order()
        commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        commission_cycle.run_weekly_statements(self.db, MON_W2, notify=False)
        self.assertTrue(self.paused())
        # Admin records a $15 collection -> outstanding $5 <= limit.
        admin_router.create_settlement(
            payload=schemas.SettlementCreate(
                vendor_id=self.vendor.id, source="commission_collection",
                amount=Decimal("15"), method="cash",
            ),
            db=self.db, admin=self.admin,
        )
        self.assertFalse(self.paused())

    def test_partial_collection_keeps_pause(self):
        self.set_limit("10")
        self.add_direct_order()
        self.vendor.direct_pay_paused = True
        self.db.commit()
        admin_router.create_settlement(
            payload=schemas.SettlementCreate(
                vendor_id=self.vendor.id, source="commission_collection",
                amount=Decimal("5"), method="cash",
            ),
            db=self.db, admin=self.admin,
        )
        self.assertTrue(self.paused())  # $15 still outstanding > $10

    def test_manual_override_endpoint(self):
        result = admin_router.set_direct_pay_pause(
            self.vendor.id, schemas.DirectPayPauseIn(paused=True),
            db=self.db, admin=self.admin,
        )
        self.assertTrue(result["direct_pay_paused"])
        self.assertTrue(self.paused())
        result = admin_router.set_direct_pay_pause(
            self.vendor.id, schemas.DirectPayPauseIn(paused=False),
            db=self.db, admin=self.admin,
        )
        self.assertFalse(result["direct_pay_paused"])
        with self.assertRaises(HTTPException) as ctx:
            admin_router.set_direct_pay_pause(
                99999, schemas.DirectPayPauseIn(paused=True),
                db=self.db, admin=self.admin,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class PausedCheckoutTests(CycleBase):
    def setUp(self):
        super().setUp()
        self.dish = models.Dish(
            vendor_id=self.vendor.id, name="Koshari",
            price=Decimal("12.00"), available=True,
        )
        self.db.add(self.dish)
        self.vendor.direct_pay_paused = True
        self.db.commit()
        self.pickup_at = datetime.now(timezone.utc) + timedelta(hours=2)

    def _single(self, method):
        return orders_router.create_order(
            payload=schemas.OrderCreate(
                vendor_id=self.vendor.id,
                items=[schemas.OrderItemIn(dish_id=self.dish.id, quantity=1)],
                fulfillment="pickup", payment_method=method,
                pickup_at=self.pickup_at,
            ),
            user=self.customer, db=self.db,
        )

    def _group(self):
        return schemas.CheckoutGroupIn(
            vendor_id=self.vendor.id,
            items=[schemas.OrderItemIn(dish_id=self.dish.id, quantity=1)],
            fulfillment="pickup", pickup_at=self.pickup_at,
        )

    def test_single_direct_methods_rejected_card_ok(self):
        for method in ("cash", "zelle", "venmo"):
            with self.assertRaises(HTTPException) as ctx:
                self._single(method)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("paused", ctx.exception.detail.lower())
        order = self._single("credit_card")
        self.assertEqual(order.payment_method, "credit_card")

    def test_multi_direct_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            orders_router.checkout_multi(
                payload=schemas.CheckoutMultiIn(
                    groups=[self._group()], payment_method="cash",
                ),
                request=_request(), user=self.customer, db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        result = orders_router.checkout_multi(
            payload=schemas.CheckoutMultiIn(
                groups=[self._group()], payment_method="credit_card",
            ),
            request=_request(), user=self.customer, db=self.db,
        )
        self.assertEqual(len(result.orders), 1)

    def test_guest_direct_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            orders_router.checkout_guest(
                payload=schemas.GuestCheckoutIn(
                    guest=schemas.GuestInfo(name="Guest", phone="555-0100"),
                    groups=[self._group()], payment_method="venmo",
                ),
                request=_request(), db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_unpaused_vendor_accepts_direct(self):
        self.vendor.direct_pay_paused = False
        self.db.commit()
        order = self._single("zelle")
        self.assertEqual(order.payment_method, "zelle")


class GuardAndScopingTests(CycleBase):
    def _dep_calls(self, router, path, method):
        route = next(
            r for r in router.routes if r.path == path and method in r.methods
        )
        calls = set()

        def walk(dep):
            calls.add(dep.call)
            for sub in dep.dependencies:
                walk(sub)

        for dep in route.dependant.dependencies:
            walk(dep)
        return calls

    def test_cycle_routes_are_admin_only(self):
        for path, method in (
            ("/api/admin/commission-cycle/status", "GET"),
            ("/api/admin/commission-cycle/run", "POST"),
            ("/api/admin/vendors/{vendor_id}/direct-pay-pause", "POST"),
        ):
            self.assertIn(
                auth.require_admin,
                self._dep_calls(admin_router.router, path, method),
                f"{method} {path} must require admin",
            )
        # Staff and vendors alike are rejected by that dependency.
        for user in (self.staff, self.owner):
            with self.assertRaises(HTTPException) as ctx:
                auth.require_admin(user=user)
            self.assertEqual(ctx.exception.status_code, 403)

    def test_cycle_status_payload(self):
        self.set_limit("10")
        self.add_direct_order()
        self.vendor.direct_pay_paused = True
        self.db.commit()
        status = admin_router.commission_cycle_status(db=self.db, admin=self.admin)
        self.assertEqual(status["pause_limit"], 10.0)
        self.assertEqual(status["statement_weekday"], 0)
        row = next(v for v in status["vendors"] if v["vendor_id"] == self.vendor.id)
        self.assertTrue(row["direct_pay_paused"])
        self.assertEqual(row["outstanding_commission"], 20.0)

    def test_statements_endpoint_own_shops_only(self):
        commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        # A second vendor with its own statement.
        owner2 = models.User(
            email="other@example.com", hashed_password="x", role="vendor",
        )
        self.db.add(owner2)
        self.db.flush()
        vendor2 = models.Vendor(owner_id=owner2.id, name="Other Kitchen")
        self.db.add(vendor2)
        self.db.commit()
        commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)

        mine = vendors_router.my_commission_statements(db=self.db, user=self.owner)
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["vendor_id"], self.vendor.id)
        self.assertEqual(mine[0]["week_key"], self.statements()[0].week_key)
        theirs = vendors_router.my_commission_statements(db=self.db, user=owner2)
        self.assertEqual(len(theirs), 1)
        self.assertEqual(theirs[0]["vendor_id"], vendor2.id)


class SchedulerTests(CycleBase):
    def test_env_guard_disables_scheduler_start(self):
        from app import main as app_main

        self.assertFalse(app_main._cycle_scheduler_enabled())  # set at module top
        app_main._cycle_task = None
        asyncio.run(app_main._start_cycle_scheduler())
        self.assertIsNone(app_main._cycle_task)
        old = os.environ.pop("DISABLE_CYCLE_SCHEDULER")
        try:
            self.assertTrue(app_main._cycle_scheduler_enabled())
        finally:
            os.environ["DISABLE_CYCLE_SCHEDULER"] = old

    def test_maybe_run_due_respects_weekday(self):
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        # Weekday already reached this week -> due.
        row = models.Setting(
            key="commission_statement_weekday", value=str(today.weekday()),
        )
        self.db.add(row)
        self.db.commit()
        summary = commission_cycle.maybe_run_due(self.db)
        self.assertIsNotNone(summary)
        # Statements now exist for this week -> not due again.
        self.assertIsNone(commission_cycle.maybe_run_due(self.db))
        # A weekday later this week than today -> not due. (Only testable
        # when today is not Sunday; the due-branch above covers the rest.)
        if today.weekday() < 6:
            self.db.query(models.CommissionStatement).delete()
            row.value = str(today.weekday() + 1)
            self.db.commit()
            self.assertIsNone(commission_cycle.maybe_run_due(self.db))


class EpisodeResetTests(CycleBase):
    """Security M1 regression: 'warned' is per-episode LIVE state, not
    all-time statement history. A vendor who settles an episode and
    later runs up NEW debt must get a fresh warning week before any
    pause — statements stay immutable history either way."""

    def settle_via_admin(self, amount):
        return admin_router.create_settlement(
            payload=schemas.SettlementCreate(
                vendor_id=self.vendor.id, source="commission_collection",
                amount=Decimal(amount), method="cash",
            ),
            db=self.db, admin=self.admin,
        )

    def test_settled_episode_gets_fresh_warning(self):
        self.set_limit("10")
        self.add_direct_order()  # $20 due > $10 limit
        s1 = commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        self.assertEqual(s1["reminded"], [self.vendor.id])
        self.assertTrue(self.warned())

        # Settle to $0.00 through the real settlement endpoint: the
        # settle event itself closes the episode — NO weekly run between.
        self.settle_via_admin("20.00")
        self.assertFalse(self.paused())
        self.assertFalse(self.warned())

        # NEW debt (a fresh episode): due $40, collected $20 -> $20 over.
        self.add_direct_order()
        s2 = commission_cycle.run_weekly_statements(self.db, MON_W2, notify=False)
        self.assertEqual(s2["reminded"], [self.vendor.id])  # warned AGAIN
        self.assertEqual(s2["paused"], [])                   # NOT paused
        stmt2 = self.statements()[1]
        self.assertTrue(stmt2.reminded)
        self.assertFalse(stmt2.pause_applied)
        self.assertFalse(self.paused())
        # History is immutable: the week-1 statement keeps its reminder.
        self.assertTrue(self.statements()[0].reminded)

        # Still over the following week -> the NEW episode's pause lands.
        s3 = commission_cycle.run_weekly_statements(self.db, MON_W3, notify=False)
        self.assertEqual(s3["paused"], [self.vendor.id])
        self.assertTrue(self.statements()[2].pause_applied)
        self.assertTrue(self.paused())

    def test_settle_while_paused_clears_warning_and_pause(self):
        self.set_limit("10")
        self.add_direct_order()
        commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        commission_cycle.run_weekly_statements(self.db, MON_W2, notify=False)
        self.assertTrue(self.paused())
        self.assertTrue(self.warned())

        # Settle to $5 (<= limit) while paused: the pause lifts
        # immediately AND the episode's warning clears with it.
        self.settle_via_admin("15.00")
        self.assertFalse(self.paused())
        self.assertFalse(self.warned())

        # A later fresh episode starts with a warning, not a pause.
        self.add_direct_order()  # due $40 - collected $15 = $25 outstanding
        s3 = commission_cycle.run_weekly_statements(self.db, MON_W3, notify=False)
        self.assertEqual(s3["reminded"], [self.vendor.id])
        self.assertEqual(s3["paused"], [])
        self.assertFalse(self.paused())


class ConcurrentRunTests(CycleBase):
    """Security L1: a lost race on the weekly run must not 500. The
    (vendor_id, week_key) unique constraint keeps the data clean — the
    loser rolls back and reports the already-run state (0 created)."""

    def _integrity_error(self):
        return IntegrityError(
            "INSERT INTO commission_statements ...", {},
            Exception("UNIQUE constraint failed: vendor_id, week_key"),
        )

    def test_integrity_error_returns_already_run_summary(self):
        self.set_limit("10")
        self.add_direct_order()
        with patch.object(self.db, "commit", side_effect=self._integrity_error()):
            summary = commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        self.assertRegex(summary["week_key"], r"^\d{4}-W\d{2}$")
        self.assertEqual(summary["statements_created"], 0)
        self.assertEqual(summary["reminded"], [])
        self.assertEqual(summary["paused"], [])
        self.assertEqual(summary["unpaused"], [])
        # The loser's work was rolled back, not half-written.
        self.assertEqual(len(self.statements()), 0)
        self.assertFalse(self.warned())
        # And a clean run afterwards behaves normally.
        clean = commission_cycle.run_weekly_statements(self.db, MON_W1, notify=False)
        self.assertEqual(clean["statements_created"], 1)
        self.assertEqual(len(self.statements()), 1)

    def test_run_endpoint_survives_lost_race(self):
        self.set_limit("10")
        self.add_direct_order()
        real_commit = self.db.commit
        calls = {"n": 0}

        def flaky_commit():
            calls["n"] += 1
            if calls["n"] == 1:  # the cycle's commit loses the race
                raise self._integrity_error()
            return real_commit()  # the endpoint's audit-log commit lands

        with patch.object(self.db, "commit", side_effect=flaky_commit):
            result = admin_router.commission_cycle_run(db=self.db, admin=self.admin)
        self.assertEqual(result["statements_created"], 0)
        self.assertEqual(len(self.statements()), 0)
        result = admin_router.commission_cycle_run(db=self.db, admin=self.admin)
        self.assertEqual(result["statements_created"], 1)
        self.assertEqual(len(self.statements()), 1)


class CommissionWarnedMigrationTests(unittest.TestCase):
    """Pre-fix DBs (vendors table without commission_warned) gain the
    column from ensure_schema: twice-safe, existing rows default to
    False (no open warning episode), old statements untouched."""

    def test_ensure_schema_adds_commission_warned(self):
        import datetime as dt

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_engine(f"sqlite:///{path}")
        try:
            models.Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            db = Session()
            owner = models.User(
                email="mig@example.com", hashed_password="x", role="vendor",
            )
            db.add(owner)
            db.flush()
            vendor = models.Vendor(owner_id=owner.id, name="Legacy Kitchen")
            db.add(vendor)
            db.flush()
            vendor_id = vendor.id
            db.add(models.CommissionStatement(
                vendor_id=vendor_id, week_key="2026-W40",
                period_start=dt.date(2026, 10, 5), period_end=dt.date(2026, 10, 11),
                direct_sales=Decimal("200"), commission_due=Decimal("20"),
                commission_collected=Decimal("0"), outstanding=Decimal("20"),
                reminded=True,
            ))
            db.commit()
            db.close()

            # Roll the schema back to its pre-fix shape.
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE vendors DROP COLUMN commission_warned"))
            with engine.connect() as conn:
                cols = {r[1] for r in conn.execute(text("PRAGMA table_info(vendors)"))}
            self.assertNotIn("commission_warned", cols)

            with patch.object(database_module, "engine", engine), \
                    patch.object(database_module, "SessionLocal", Session):
                database_module.ensure_schema()
                database_module.ensure_schema()  # second run must be a no-op

            with engine.connect() as conn:
                cols = {r[1] for r in conn.execute(text("PRAGMA table_info(vendors)"))}
            self.assertIn("commission_warned", cols)
            db = Session()
            legacy = db.get(models.Vendor, vendor_id)
            self.assertFalse(bool(legacy.commission_warned))
            self.assertFalse(bool(legacy.direct_pay_paused))
            stmts = list(db.scalars(select(models.CommissionStatement)))
            self.assertEqual(len(stmts), 1)
            self.assertTrue(stmts[0].reminded)  # history intact
            db.close()
        finally:
            engine.dispose()
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
