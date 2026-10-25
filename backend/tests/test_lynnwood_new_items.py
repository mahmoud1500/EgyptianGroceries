"""Oct 2026 Lynnwood additions: Feseekh, Renga, Whole Wheat Bread at $2.

The vendor already exists on the live DB, so GROCERY_ITEMS alone can't
reach it — the fill_seed_data backfill must add just these three, only
where missing, with Arabic names, and stay idempotent.
"""
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.seed import DISH_NAMES_AR, GROCERY_ITEMS, fill_seed_data

NEW_ITEMS = {
    "Feseekh": "فسيخ",
    "Renga": "رنجة",
    "Whole Wheat Bread": "عيش حبة كاملة",
}


class LynnwoodNewItemsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _make_vendor(self):
        v = models.Vendor(
            name="Lynnwood Groceries",
            tagline="Egyptian pantry staples, spices & sweets",
            area="Everett, WA",
            phone="206-555-0345",
            fulfillment="both",
            delivery_fee=Decimal("3.99"),
            name_ar="بقالة لينوود",
        )
        self.db.add(v)
        self.db.flush()
        self.db.add(
            models.Dish(
                vendor_id=v.id,
                name="Existing Item",
                description="",
                price=Decimal("4.99"),
                category="Pantry",
            )
        )
        self.db.commit()
        return v.id

    def test_backfill_adds_three_with_prices_and_arabic(self):
        vid = self._make_vendor()
        fill_seed_data(self.db)
        self.db.expire_all()
        dishes = {
            d.name: d
            for d in self.db.query(models.Dish).filter_by(vendor_id=vid).all()
        }
        self.assertEqual(len(dishes), 4)
        self.assertIn("Existing Item", dishes)
        for name, name_ar in NEW_ITEMS.items():
            self.assertIn(name, dishes)
            self.assertEqual(float(dishes[name].price), 2.00)
            self.assertEqual(dishes[name].category, "Pantry")
            self.assertEqual(dishes[name].name_ar, name_ar)

    def test_backfill_idempotent(self):
        vid = self._make_vendor()
        fill_seed_data(self.db)
        fill_seed_data(self.db)
        self.db.expire_all()
        self.assertEqual(
            self.db.query(models.Dish).filter_by(vendor_id=vid).count(), 4
        )

    def test_seed_list_and_arabic_names(self):
        by_name = {item[0]: item for item in GROCERY_ITEMS}
        for name, name_ar in NEW_ITEMS.items():
            self.assertIn(name, by_name)
            self.assertEqual(by_name[name][2], 2.00)
            self.assertEqual(DISH_NAMES_AR[name], name_ar)


if __name__ == "__main__":
    unittest.main()
