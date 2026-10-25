"""v58: Arabic names + descriptions for Alpha-T Grocery.

The 149 items shipped in v55 with English names only, so Arabic mode
fell back to English for the whole shelf. _ensure_alpha_t_arabic must
fill name_ar + description_ar on the existing rows (and the vendor's
name_ar), only where empty, and stay idempotent; fresh creation via
_add_dishes must already carry the Arabic values.
"""
import re
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.seed import (
    ALPHA_T_DESCS_AR,
    ALPHA_T_ITEMS,
    ALPHA_T_NAMES_AR,
    _ensure_alpha_t,
    _ensure_alpha_t_arabic,
)

SAMPLE = [
    "Bab El Sham 7 Spices Mix",
    "El Rashidi El Mizan Chocolate Halawa Spread, 300g",
    "Domty Istanbolly White Cheese",
]


class AlphaTArabicTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _make_legacy_vendor(self):
        """Alpha-T as it exists on the live DB: English names only."""
        v = models.Vendor(
            name="Alpha-T Grocery",
            tagline="Mediterranean & Egyptian grocery — Everett",
            area="Everett, WA",
            phone="",
            fulfillment="both",
            delivery_fee=Decimal("3.99"),
        )
        self.db.add(v)
        self.db.flush()
        for name in SAMPLE:
            desc = next(d for n, d, p, c, f in ALPHA_T_ITEMS if n == name)
            self.db.add(
                models.Dish(
                    vendor_id=v.id,
                    name=name,
                    description=desc,
                    price=Decimal("4.99"),
                    category="Pantry",
                )
            )
        self.db.commit()
        return v

    def test_backfill_fills_names_descriptions_and_vendor(self):
        v = self._make_legacy_vendor()
        _ensure_alpha_t_arabic(self.db)
        self.db.refresh(v)
        self.assertEqual(v.name_ar, "بقالة ألفا-تي")
        for name in SAMPLE:
            d = (
                self.db.query(models.Dish)
                .filter_by(vendor_id=v.id, name=name)
                .one()
            )
            self.assertEqual(d.name_ar, ALPHA_T_NAMES_AR[name], name)
            self.assertEqual(d.description_ar, ALPHA_T_DESCS_AR[name], name)

    def test_backfill_preserves_vendor_edits(self):
        v = self._make_legacy_vendor()
        v.name_ar = "اسم مخصص"
        dish = self.db.query(models.Dish).filter_by(name=SAMPLE[0]).one()
        dish.name_ar = "اسم طبق مخصص"
        dish.description_ar = "وصف مخصص"
        self.db.commit()
        _ensure_alpha_t_arabic(self.db)
        self.db.refresh(v)
        self.db.refresh(dish)
        self.assertEqual(v.name_ar, "اسم مخصص")
        self.assertEqual(dish.name_ar, "اسم طبق مخصص")
        self.assertEqual(dish.description_ar, "وصف مخصص")

    def test_backfill_is_idempotent(self):
        v = self._make_legacy_vendor()
        _ensure_alpha_t_arabic(self.db)
        first = {
            d.name: (d.name_ar, d.description_ar)
            for d in self.db.query(models.Dish).all()
        }
        _ensure_alpha_t_arabic(self.db)
        second = {
            d.name: (d.name_ar, d.description_ar)
            for d in self.db.query(models.Dish).all()
        }
        self.assertEqual(first, second)
        self.assertEqual(self.db.query(models.Dish).count(), len(SAMPLE))

    def test_backfill_noops_without_vendor(self):
        _ensure_alpha_t_arabic(self.db)  # must not raise on an empty DB
        self.assertEqual(self.db.query(models.Dish).count(), 0)

    def test_fresh_creation_carries_arabic_values(self):
        _ensure_alpha_t(self.db)
        dishes = self.db.query(models.Dish).all()
        self.assertEqual(len(dishes), len(ALPHA_T_ITEMS))
        missing = [d.name for d in dishes if not d.name_ar or not d.description_ar]
        self.assertEqual(missing, [])

    def test_dicts_cover_exactly_the_catalog(self):
        names = [n for n, d, p, c, f in ALPHA_T_ITEMS]
        self.assertEqual(set(ALPHA_T_NAMES_AR), set(names))
        self.assertEqual(set(ALPHA_T_DESCS_AR), set(names))
        for name in names:
            self.assertTrue(ALPHA_T_NAMES_AR[name].strip(), name)
            self.assertTrue(ALPHA_T_DESCS_AR[name].strip(), name)
            self.assertIsNone(
                re.search(r"[A-Za-z]", ALPHA_T_NAMES_AR[name] + ALPHA_T_DESCS_AR[name]),
                name,
            )


if __name__ == "__main__":
    unittest.main()
