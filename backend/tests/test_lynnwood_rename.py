"""Rename backfill: Nile Groceries -> Lynnwood Groceries (Oct 2026).

fill_seed_data runs on every startup, so an existing database whose
vendor row still says "Nile Groceries" must be renamed in place, with
its dishes untouched. A vendor's custom Arabic name is never overwritten.
"""
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.seed import fill_seed_data


class RenameBackfillTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _make_old_vendor(self, name_ar):
        v = models.Vendor(
            name="Nile Groceries",
            tagline="Egyptian pantry staples, spices & sweets",
            area="Everett, WA",
            phone="206-555-0345",
            fulfillment="both",
            delivery_fee=Decimal("3.99"),
            name_ar=name_ar,
        )
        self.db.add(v)
        self.db.flush()
        self.db.add(
            models.Dish(
                vendor_id=v.id,
                name="Test Beans",
                description="",
                price=Decimal("4.99"),
                category="Pantry",
            )
        )
        self.db.commit()
        return v.id

    def test_old_name_renamed_items_preserved_arabic_updated(self):
        vid = self._make_old_vendor("بقالة النيل")
        fill_seed_data(self.db)
        v = self.db.query(models.Vendor).filter_by(id=vid).one()
        self.assertEqual(v.name, "Lynnwood Groceries")
        self.assertEqual(v.name_ar, "بقالة لينوود")
        self.assertEqual(
            self.db.query(models.Dish).filter_by(vendor_id=vid).count(), 1
        )
        self.assertIsNone(
            self.db.query(models.Vendor).filter_by(name="Nile Groceries").first()
        )

    def test_custom_arabic_name_preserved(self):
        vid = self._make_old_vendor("بقالتي الخاصة")
        fill_seed_data(self.db)
        v = self.db.query(models.Vendor).filter_by(id=vid).one()
        self.assertEqual(v.name, "Lynnwood Groceries")
        self.assertEqual(v.name_ar, "بقالتي الخاصة")


if __name__ == "__main__":
    unittest.main()
