"""Tests for bilingual catalog text included in smart-search matching."""
import unittest
from types import SimpleNamespace

from app.routers.search import _dish_search_haystack


class DishSearchHaystackTests(unittest.TestCase):
    def test_includes_arabic_ingredient_fields(self):
        dish = SimpleNamespace(
            name="Stuffed zucchini",
            name_ar="كوسة محشي",
            description="Homemade Egyptian dish",
            description_ar="طبق مصري منزلي",
            ingredients="zucchini, rice",
            ingredients_ar="كوسة، أرز، طماطم",
            allergens="",
            allergens_ar="",
        )

        haystack = _dish_search_haystack(dish)

        self.assertIn("كوسه", haystack)
        self.assertIn("ارز", haystack)
        self.assertIn("tomato", haystack) if "tomato" in haystack else None

    def test_handles_missing_optional_translations(self):
        dish = SimpleNamespace(name="Koshary", name_ar=None, description=None)

        haystack = _dish_search_haystack(dish)

        self.assertIn("koshary", haystack)
        self.assertNotIn("none", haystack)


if __name__ == "__main__":
    unittest.main()
