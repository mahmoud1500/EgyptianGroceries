"""Remove demo seed data before going live.

Run ONCE on the production database (after seeding, before launch):

    cd backend
    python -m app.clean_demo

What it removes:
  - The three demo accounts: customer@demo.com, vendor@demo.com, admin@demo.com
    (all with the publicly known password "demo1234")
  - Orders placed by the demo customer (and their order items)
  - Every row that FK-references a demo user directly (not via orders):
    admin audit-log rows, reviews, favorites, password-reset tokens,
    push tokens, complaints filed by a demo user, and loyalty-ledger rows
    (including non-order `adjust` rows with order_id NULL). Without these
    the user deletes fail with an FK violation on Postgres — and the
    realistic launch path has the demo admin poking the back-office first,
    so a single logged action would otherwise leave the publicly-known
    demo accounts in production with a crashing cleanup script.

What it deliberately KEEPS:
  - Vendors and dishes (e.g. Omar Caboose is a real business). Vendors owned
    by vendor@demo.com are detached (owner set to NULL) — assign a real owner
    afterwards via the admin back-office or seed.

Safe to re-run: anything already gone is simply skipped.
"""
import os
import sys

from sqlalchemy import delete, select

from .database import SessionLocal, engine
from . import models

DEMO_EMAILS = ("customer@demo.com", "vendor@demo.com", "admin@demo.com")


def clean_demo(confirm: bool = True) -> dict:
    db = SessionLocal()
    removed = {"users": 0, "orders": 0, "order_items": 0, "order_events": 0,
               "order_messages": 0, "loyalty_ledger": 0, "complaints": 0,
               "stock_movements": 0, "admin_audit_log": 0, "reviews": 0,
               "favorites": 0, "password_reset_tokens": 0, "push_tokens": 0,
               "detached_vendors": []}
    try:
        users = list(
            db.scalars(select(models.User).where(models.User.email.in_(DEMO_EMAILS))).all()
        )
        if not users:
            print("No demo accounts found — nothing to do.")
            return removed

        print("Will remove:")
        for u in users:
            print(f"  - {u.email} ({u.role})")
        demo_ids = [u.id for u in users]
        cust_ids = [u.id for u in users if u.role == "customer"]
        order_ids: list[int] = []
        if cust_ids:
            order_ids = [o.id for o in db.scalars(
                select(models.Order).where(models.Order.customer_id.in_(cust_ids))).all()]
            print(f"  - {len(order_ids)} demo order(s) (+ their items)")
        owned = list(
            db.scalars(select(models.Vendor).where(models.Vendor.owner_id.in_(demo_ids))).all()
        )
        for v in owned:
            print(f"  - detach vendor '{v.name}' from its demo owner (owner -> NULL)")

        if confirm:
            answer = input("\nType YES to permanently delete the above: ").strip()
            if answer != "YES":
                print("Aborted — nothing was changed.")
                return removed

        if order_ids:
            # Order-dependent rows first: OrderEvent/OrderMessage/
            # Complaint/StockMovement all FK-reference orders with no
            # cascade. Deleting the orders without these fails with an FK
            # violation on Postgres (and on SQLite now that FK enforcement
            # is on — DBA P0-3). Bulk deletes bypass ORM cascades, so each
            # table is cleared explicitly. LoyaltyLedger is NOT deleted here:
            # it is deleted by user_id below, which also catches non-order
            # `adjust` rows (order_id NULL) that an order-based delete misses.
            removed["order_events"] = db.execute(
                delete(models.OrderEvent).where(models.OrderEvent.order_id.in_(order_ids))
            ).rowcount or 0
            removed["order_messages"] = db.execute(
                delete(models.OrderMessage).where(models.OrderMessage.order_id.in_(order_ids))
            ).rowcount or 0
            # LoyaltyLedger rows with order_id pointing at a demo order
            # (reason 'earn', written by award_completion_points when an
            # order is completed) must go BEFORE the orders: the FK has no
            # ON DELETE CASCADE, so deleting orders first raises
            # ForeignKeyViolation on Postgres and rolls the whole cleanup
            # back. The user-based loyalty delete below still handles
            # order_id IS NULL adjust rows.
            removed["loyalty_ledger"] += db.execute(
                delete(models.LoyaltyLedger).where(
                    models.LoyaltyLedger.order_id.in_(order_ids))
            ).rowcount or 0
            removed["complaints"] = db.execute(
                delete(models.Complaint).where(models.Complaint.order_id.in_(order_ids))
            ).rowcount or 0
            removed["stock_movements"] = db.execute(
                delete(models.StockMovement).where(models.StockMovement.order_id.in_(order_ids))
            ).rowcount or 0
            removed["order_items"] = db.execute(
                delete(models.OrderItem).where(models.OrderItem.order_id.in_(order_ids))
            ).rowcount or 0
            removed["orders"] = db.execute(
                delete(models.Order).where(models.Order.id.in_(order_ids))
            ).rowcount or 0

        # Rows that FK-reference demo users DIRECTLY (not via orders).
        # Each one blocks the user deletes below with an FK violation if
        # left behind — e.g. one logged admin action (settings PUT, refund,
        # ...) leaves an admin_audit_log row pointing at admin@demo.com and
        # the whole cleanup crashes, leaving the demo accounts in place.
        # Complaints are deleted by reporter_id here too: the order-based
        # delete above only catches complaints attached to a demo order.
        removed["admin_audit_log"] = db.execute(
            delete(models.AdminAuditLog).where(
                models.AdminAuditLog.admin_user_id.in_(demo_ids))
        ).rowcount or 0
        removed["reviews"] = db.execute(
            delete(models.Review).where(models.Review.user_id.in_(demo_ids))
        ).rowcount or 0
        removed["favorites"] = db.execute(
            delete(models.Favorite).where(models.Favorite.user_id.in_(demo_ids))
        ).rowcount or 0
        removed["password_reset_tokens"] = db.execute(
            delete(models.PasswordResetToken).where(
                models.PasswordResetToken.user_id.in_(demo_ids))
        ).rowcount or 0
        removed["push_tokens"] = db.execute(
            delete(models.PushToken).where(models.PushToken.user_id.in_(demo_ids))
        ).rowcount or 0
        removed["complaints"] += db.execute(
            delete(models.Complaint).where(models.Complaint.reporter_id.in_(demo_ids))
        ).rowcount or 0
        removed["loyalty_ledger"] += db.execute(
            delete(models.LoyaltyLedger).where(models.LoyaltyLedger.user_id.in_(demo_ids))
        ).rowcount or 0
        for v in owned:
            v.owner_id = None
            removed["detached_vendors"].append(v.name)
        for u in users:
            db.delete(u)
            removed["users"] += 1
        db.commit()
        print(
            f"\nDone: removed {removed['users']} demo user(s), {removed['orders']} order(s), "
            f"{removed['order_items']} order item(s)."
        )
        if removed["detached_vendors"]:
            print(
                "Detached vendors (no owner — assign a real owner in the admin back-office): "
                + ", ".join(removed["detached_vendors"])
            )
        print("\nNEXT: create your real admin account (see DEPLOY.md).")
        return removed
    finally:
        db.close()


if __name__ == "__main__":
    if os.environ.get("DATABASE_URL", "").startswith("sqlite"):
        print("NOTE: DATABASE_URL looks like SQLite (local dev).")
        print("Run this against PRODUCTION Postgres, e.g.:")
        print('  DATABASE_URL="postgresql+psycopg2://..." python -m app.clean_demo')
        if "--yes-sqlite" not in sys.argv:
            sys.exit(1)
    clean_demo(confirm="--yes" not in sys.argv)
