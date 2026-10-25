"""Search sort + vendor filter (Oct 2026): /api/search sort + vendor_id.

Calls the real smart_search route function (not HTTP) with a bare
starlette Request — the rate limiter only needs request.client.host.
Effective price = price after standing/flash discount, matching the
price the customer actually pays (and sees) on the dish card.
"""
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app import models
from app.routers.search import _effective_price, smart_search


def _req():
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/search",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "query_string": b"",
            "server": ("test", 80),
            "scheme": "http",
        }
    )


class SearchSortFilterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        v1 = models.Vendor(name="Vendor One", fulfillment="both")
        v2 = models.Vendor(name="Vendor Two", fulfillment="both")
        self.db.add_all([v1, v2])
        self.db.flush()
        self.v1_id, self.v2_id = v1.id, v2.id
        dishes = [
            ("Alpha Test Dish", v1.id, "10.00", 0),
            ("Beta Test Dish", v1.id, "5.00", 0),
            ("Gamma Test Dish", v1.id, "8.00", 50),
            ("Delta Test Dish", v2.id, "3.00", 0),
        ]
        for name, vid, price, disc in dishes:
            self.db.add(
                models.Dish(
                    vendor_id=vid,
                    name=name,
                    description="",
                    price=Decimal(price),
                    category="Mains",
                    discount_percent=disc,
                    available=True,
                    is_hidden=False,
                )
            )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _names(self, **kw):
        # Route params carry Query() defaults, so every parameter must be
        # passed explicitly when calling the route function directly.
        params = {
            "category": None,
            "vegetarian": None,
            "vegan": None,
            "available_only": True,
            "vendor_id": None,
            "sort": "relevance",
        }
        params.update(kw)
        out = smart_search(_req(), q="test", db=self.db, caller=None, **params)
        return [h.dish.name for h in out.hits]

    def test_effective_price_applies_discount(self):
        dish = self.db.query(models.Dish).filter_by(name="Gamma Test Dish").one()
        self.assertEqual(_effective_price(dish), 4.00)

    def test_sort_price_asc(self):
        self.assertEqual(
            self._names(sort="price_asc"),
            ["Delta Test Dish", "Gamma Test Dish", "Beta Test Dish", "Alpha Test Dish"],
        )

    def test_sort_price_desc(self):
        self.assertEqual(
            self._names(sort="price_desc"),
            ["Alpha Test Dish", "Beta Test Dish", "Gamma Test Dish", "Delta Test Dish"],
        )

    def test_vendor_filter(self):
        self.assertEqual(self._names(vendor_id=self.v2_id), ["Delta Test Dish"])

    def test_vendor_filter_combines_with_sort(self):
        self.assertEqual(
            self._names(vendor_id=self.v1_id, sort="price_asc"),
            ["Gamma Test Dish", "Beta Test Dish", "Alpha Test Dish"],
        )

    def test_default_is_relevance_name_order(self):
        self.assertEqual(
            self._names(),
            ["Alpha Test Dish", "Beta Test Dish", "Delta Test Dish", "Gamma Test Dish"],
        )

    def test_unknown_sort_falls_back_to_relevance(self):
        self.assertEqual(
            self._names(sort="bogus"),
            ["Alpha Test Dish", "Beta Test Dish", "Delta Test Dish", "Gamma Test Dish"],
        )


if __name__ == "__main__":
    unittest.main()
