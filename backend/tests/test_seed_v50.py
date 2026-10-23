"""v50: featured best-sellers backfill tests.

`fill_seed_data` runs on every app startup (in-place zip upgrades never
re-run `python -m app.seed`), so the v50 featured flags must land on
databases seeded before v50 — and stay stable on repeat boots without
touching dishes outside the best-seller list.
"""
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.seed import FEATURED_BEST_SELLERS, fill_seed_data


class FeaturedBackfillTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        vendor = models.Vendor(name="Test Kitchen", fulfillment="pickup")
        self.db.add(vendor)
        self.db.flush()
        self.vendor_id = vendor.id
        # One dish per best-seller name, all un-featured (a pre-v50 DB).
        for name in FEATURED_BEST_SELLERS:
            self.db.add(
                models.Dish(
                    vendor_id=vendor.id,
                    name=name,
                    description="",
                    price=Decimal("9.99"),
                    category="Mains",
                    is_featured=False,
                )
            )
        # A dish outside the list must never be flipped by the backfill.
        self.db.add(
            models.Dish(
                vendor_id=vendor.id,
                name="Some Other Dish",
                description="",
                price=Decimal("1.00"),
                category="Mains",
                is_featured=False,
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _featured_names(self):
        rows = (
            self.db.query(models.Dish)
            .filter(models.Dish.is_featured == True)  # noqa: E712
            .all()
        )
        return {d.name for d in rows}

    def test_backfill_flags_exactly_the_best_sellers(self):
        fill_seed_data(self.db)
        self.assertEqual(self._featured_names(), set(FEATURED_BEST_SELLERS))

    def test_backfill_is_idempotent_across_boots(self):
        fill_seed_data(self.db)
        first = self._featured_names()
        fill_seed_data(self.db)
        fill_seed_data(self.db)
        self.assertEqual(self._featured_names(), first)
        count = self.db.query(models.Dish).count()
        self.assertEqual(count, len(FEATURED_BEST_SELLERS) + 1)


if __name__ == "__main__":
    unittest.main()
