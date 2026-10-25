"""Search ranking (Oct 2026): name matches must outrank description
matches, and alias groups must not over-expand.

Regression: searching "Bread" returned 40 dishes all tied at score 3
(grill plates whose descriptions mention bread tied with Baladi Bread
itself) and sorted alphabetically, so liver and kebab plates came
first. A second cause: "bread" expanded the "om ali" alias group
because "bread" is a substring of "bread pudding".
Calls the real smart_search route function (see test_search_sort_filter).
"""
import unittest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app import models
from app.routers.search import _expand_query, smart_search


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


def _params(**kw):
    params = {
        "category": None,
        "vegetarian": None,
        "vegan": None,
        "available_only": True,
        "vendor_id": None,
        "sort": "relevance",
    }
    params.update(kw)
    return params


class SearchRankingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        v = models.Vendor(name="Vendor One", fulfillment="both")
        self.db.add(v)
        self.db.flush()
        for name, desc, name_ar in [
            ("Baladi Bread", "Freshly baked bread", "عيش بلدي"),
            ("Grill Plate", "Served with baladi bread and salad", None),
            ("Om Ali", "Sweet milk pudding with nuts", "أم علي"),
            ("Koshary", "Rice, pasta and lentils", "كشري"),
        ]:
            self.db.add(
                models.Dish(
                    vendor_id=v.id,
                    name=name,
                    name_ar=name_ar,
                    description=desc,
                    price=Decimal("5.00"),
                    category="Mains",
                    available=True,
                    is_hidden=False,
                )
            )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _search(self, q):
        out = smart_search(_req(), q=q, db=self.db, caller=None, **_params())
        return [(h.dish.name, h.score) for h in out.hits]

    def test_expand_bread_does_not_pull_om_ali(self):
        self.assertEqual(_expand_query("bread"), ["bread"])

    def test_expand_full_phrase_still_works(self):
        needles = _expand_query("bread pudding")
        self.assertIn("om ali", needles)
        self.assertIn("bread pudding", needles)

    def test_expand_term_inside_longer_query(self):
        needles = _expand_query("chicken koshary")
        self.assertIn("koshary", needles)
        self.assertIn("كشري", needles)

    def test_bread_name_match_ranks_above_description_match(self):
        self.assertEqual(
            self._search("bread"),
            [("Baladi Bread", 4), ("Grill Plate", 3)],
        )

    def test_bread_does_not_return_om_ali(self):
        names = [n for n, _ in self._search("bread")]
        self.assertNotIn("Om Ali", names)

    def test_arabic_name_match_scores_top(self):
        self.assertEqual(self._search("كشري"), [("Koshary", 4)])


if __name__ == "__main__":
    unittest.main()
