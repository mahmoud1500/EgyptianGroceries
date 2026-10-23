"""v51: ingredients coverage for the last 9 prepared plates.

`fill_seed_data` runs on every app startup and fills `Dish.ingredients`
from `DISH_INGREDIENTS` only when empty. Nine prepared plates had no
dict entry (Koshary, Molokhia, Fatta, the hawawshi plate, Om Ali,
Basbousa, Kahk, Baladi Bread, Feteer) — v51 adds them. Grocery items
must stay ingredient-free, and a vendor's own edit must never be
overwritten by the fill.
"""
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.seed import GROCERY_ITEMS, OMAR_MENU, SAMPLE_VENDORS, fill_seed_data

NINE_PLATES = [
    "Koshary",
    "Molokhia with Chicken",
    "Fatta",
    "Charcoal-Grilled Hawawshi (Plate)",
    "Om Ali",
    "Basbousa",
    "Kahk",
    "Baladi Bread (5 pc)",
    "Feteer Meshaltet",
]


class IngredientsCoverageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

        def add_menu(vendor_name, items):
            vendor = models.Vendor(name=vendor_name, fulfillment="pickup")
            self.db.add(vendor)
            self.db.flush()
            for name, desc, price, category, featured in items:
                self.db.add(
                    models.Dish(
                        vendor_id=vendor.id,
                        name=name,
                        description=desc,
                        price=Decimal(str(price)),
                        category=category,
                        is_featured=featured,
                    )
                )

        # Same dish rows a fresh `python -m app.seed` creates.
        add_menu("Omar Caboose", OMAR_MENU)
        for v in SAMPLE_VENDORS:
            add_menu(v["name"], v["dishes"])
        add_menu("Nile Groceries", GROCERY_ITEMS)
        self.db.commit()
        # Fresh seed + first startup fill.
        fill_seed_data(self.db)

    def tearDown(self):
        self.db.close()

    def _by_name(self, name):
        return self.db.query(models.Dish).filter(models.Dish.name == name).all()

    def test_all_nine_plates_have_ingredients(self):
        for name in NINE_PLATES:
            rows = self._by_name(name)
            self.assertTrue(rows, f"dish missing from seed: {name}")
            for dish in rows:
                self.assertTrue(
                    dish.ingredients and dish.ingredients.strip(),
                    f"no ingredients filled for: {name}",
                )

    def test_grocery_categories_have_no_ingredients(self):
        for category in ("Pantry", "Spices & Herbs"):
            rows = (
                self.db.query(models.Dish)
                .filter(models.Dish.category == category)
                .all()
            )
            self.assertTrue(rows, f"no seeded dishes in category: {category}")
            for dish in rows:
                self.assertFalse(
                    dish.ingredients,
                    f"grocery dish gained ingredients: {dish.name}",
                )

    def test_fill_never_overwrites_a_vendor_edit(self):
        dish = self._by_name("Koshary")[0]
        dish.ingredients = "Vendor's own custom list"
        self.db.commit()
        fill_seed_data(self.db)
        self.db.expire_all()
        self.assertEqual(
            self._by_name("Koshary")[0].ingredients, "Vendor's own custom list"
        )


if __name__ == "__main__":
    unittest.main()
