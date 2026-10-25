"""Vendor dedupe: heal the v55 double-create (Oct 2026).

Live v55 bug: on the first boot after deploy, seed() created the grocery
vendor BEFORE fill_seed_data ran the Nile -> Lynnwood rename, so the
lookup by the new name missed the old row, created a second "Lynnwood
Groceries" vendor + a second copy of its 33 dishes, and the rename then
renamed the old row. Live showed 2 Lynnwood rows and 326 dishes (293 + 33).

Fix: the rename runs BEFORE any vendor creation in seed(), and
fill_seed_data merges same-name vendor rows (keeping the lowest id,
moving references, deleting exact-duplicate dishes). These tests cover
both the root cause and the merge.
"""
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app import database as db_module
from app import seed as seed_module
from app.seed import fill_seed_data


def _vendor(name, **kw):
    kw.setdefault("tagline", "")
    kw.setdefault("area", "")
    kw.setdefault("phone", "")
    kw.setdefault("fulfillment", "both")
    kw.setdefault("delivery_fee", Decimal("3.99"))
    return models.Vendor(name=name, **kw)


def _dish(vendor_id, name):
    return models.Dish(
        vendor_id=vendor_id,
        name=name,
        description="",
        price=Decimal("4.99"),
        category="Pantry",
    )


class DedupeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_full_seed_with_old_nile_row_creates_no_duplicate(self):
        """The v55 live scenario: pre-existing Nile row + full seed()."""
        old = _vendor("Nile Groceries", name_ar="بقالة النيل")
        self.db.add(old)
        self.db.flush()
        self.db.add(_dish(old.id, "Test Beans"))
        self.db.commit()

        orig_engine, orig_session = seed_module.engine, seed_module.SessionLocal
        orig_db_engine = db_module.engine
        seed_module.engine = self.engine
        seed_module.SessionLocal = sessionmaker(bind=self.engine)
        # ensure_schema() reads database.engine directly, not seed.engine.
        db_module.engine = self.engine
        try:
            seed_module.seed()
        finally:
            seed_module.engine, seed_module.SessionLocal = orig_engine, orig_session
            db_module.engine = orig_db_engine

        self.db.expire_all()
        lynn = (
            self.db.query(models.Vendor)
            .filter_by(name="Lynnwood Groceries")
            .all()
        )
        self.assertEqual(len(lynn), 1)
        self.assertEqual(lynn[0].id, old.id)
        self.assertEqual(
            self.db.query(models.Dish).filter_by(vendor_id=old.id).count(), 4
        )
        self.assertIsNone(
            self.db.query(models.Vendor).filter_by(name="Nile Groceries").first()
        )

    def test_dedupe_merges_duplicate_vendors(self):
        kept = _vendor("Lynnwood Groceries", name_ar="بقالة لينوود")
        dup = _vendor("Lynnwood Groceries", name_ar="بقالة لينوود")
        self.db.add_all([kept, dup])
        self.db.flush()
        kept_a = _dish(kept.id, "Dup Dish")
        kept_b = _dish(kept.id, "Kept Only")
        dup_a = _dish(dup.id, "Dup Dish")
        dup_c = _dish(dup.id, "Dup Only")
        self.db.add_all([kept_a, kept_b, dup_a, dup_c])
        self.db.flush()
        user = models.User(
            email="t@t.com", hashed_password="x", name="T", role="customer"
        )
        self.db.add(user)
        self.db.flush()
        order = models.Order(
            vendor_id=dup.id,
            fulfillment="pickup",
            payment_method="cash",
            subtotal=Decimal("4.99"),
            total=Decimal("4.99"),
        )
        self.db.add(order)
        self.db.flush()
        item = models.OrderItem(
            order_id=order.id,
            dish_id=dup_a.id,
            dish_name="Dup Dish",
            unit_price=Decimal("4.99"),
            quantity=1,
        )
        fav = models.Favorite(user_id=user.id, dish_id=dup_a.id)
        review = models.Review(
            user_id=user.id,
            dish_id=dup_a.id,
            vendor_id=dup.id,
            rating=5,
        )
        self.db.add_all([item, fav, review])
        self.db.commit()

        fill_seed_data(self.db)
        self.db.expire_all()

        lynn = (
            self.db.query(models.Vendor)
            .filter_by(name="Lynnwood Groceries")
            .all()
        )
        self.assertEqual(len(lynn), 1)
        self.assertEqual(lynn[0].id, kept.id)
        names = sorted(
            d.name
            for d in self.db.query(models.Dish)
            .filter_by(vendor_id=kept.id)
            .all()
        )
        # Kept dishes + the reassigned unique dup dish + the Oct 2026
        # backfill's three new Lynnwood items.
        self.assertEqual(
            names,
            [
                "Dup Dish",
                "Dup Only",
                "Feseekh",
                "Kept Only",
                "Renga",
                "Whole Wheat Bread",
            ],
        )
        self.assertIsNone(
            self.db.query(models.Dish).filter_by(id=dup_a.id).first()
        )
        self.assertEqual(
            self.db.query(models.OrderItem).filter_by(id=item.id).one().dish_id,
            kept_a.id,
        )
        self.assertEqual(
            self.db.query(models.Favorite).filter_by(id=fav.id).one().dish_id,
            kept_a.id,
        )
        rev = self.db.query(models.Review).filter_by(id=review.id).one()
        self.assertEqual(rev.dish_id, kept_a.id)
        self.assertEqual(rev.vendor_id, kept.id)
        self.assertEqual(
            self.db.query(models.Order).filter_by(id=order.id).one().vendor_id,
            kept.id,
        )

    def test_dedupe_noop_on_clean_db(self):
        omar = _vendor("Omar Caboose")
        lynn = _vendor("Lynnwood Groceries")
        self.db.add_all([omar, lynn])
        self.db.flush()
        self.db.add(_dish(omar.id, "Omar Dish"))
        self.db.add(_dish(lynn.id, "Lynn Dish"))
        # The Oct 2026 backfill items are already present, so fill adds
        # nothing and the test isolates the dedupe no-op.
        self.db.add(_dish(lynn.id, "Feseekh"))
        self.db.add(_dish(lynn.id, "Renga"))
        self.db.add(_dish(lynn.id, "Whole Wheat Bread"))
        self.db.commit()

        fill_seed_data(self.db)
        self.db.expire_all()

        self.assertEqual(
            self.db.query(models.Vendor).filter_by(name="Omar Caboose").count(), 1
        )
        self.assertEqual(
            self.db.query(models.Vendor)
            .filter_by(name="Lynnwood Groceries")
            .count(),
            1,
        )
        self.assertEqual(
            self.db.query(models.Dish).filter_by(vendor_id=lynn.id).count(), 4
        )


if __name__ == "__main__":
    unittest.main()
