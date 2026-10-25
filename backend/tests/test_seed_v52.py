"""v52: Arabic dish names end-to-end.

Dishes gain `Dish.name_ar` (mirroring Bundle.name_ar) and order items gain
a `dish_name_ar` snapshot. Covers:
(a) ensure_schema migration on an old-shape DB (no name_ar columns),
(b) fill_seed_data filling all 144 seeded dishes from DISH_NAMES_AR,
    only-when-empty and idempotent,
(c) Arabic search on GET /api/dishes (q matches name_ar),
(d) order placement snapshotting dish_name_ar,
(e) DishOut exposing name_ar + vendor create/update persisting it.
"""
import os
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import database as database_module  # noqa: E402
from app import models, schemas  # noqa: E402
from app.routers import dishes as dishes_router  # noqa: E402
from app.routers import orders as orders_router  # noqa: E402
from app.seed import (  # noqa: E402
    DISH_NAMES_AR,
    GROCERY_ITEMS,
    OMAR_MENU,
    SAMPLE_VENDORS,
    UM_SOHAIB_MENU,
    fill_seed_data,
)


def _seed_all_menus(db):
    """Create the same dish rows a fresh `python -m app.seed` creates
    (names/descriptions/prices from the real menu lists), WITHOUT name_ar —
    the pre-v52 shape the fill must repair."""

    def add_menu(vendor_name, items, with_photo=False):
        vendor = models.Vendor(name=vendor_name, fulfillment="pickup")
        db.add(vendor)
        db.flush()
        for t in items:
            name, desc, price, category, featured = t[0], t[1], t[2], t[3], t[4]
            db.add(
                models.Dish(
                    vendor_id=vendor.id,
                    name=name,
                    description=desc,
                    price=Decimal(str(price)),
                    category=category,
                    is_featured=featured,
                )
            )

    add_menu("Omar Caboose", OMAR_MENU)
    for v in SAMPLE_VENDORS:
        add_menu(v["name"], v["dishes"])
    add_menu("Lynnwood Groceries", GROCERY_ITEMS)
    add_menu("Um Sohaib's Kitchen", UM_SOHAIB_MENU, with_photo=True)
    db.commit()


class ArabicNameFillTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        _seed_all_menus(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_seed_menus_cover_exactly_the_dict(self):
        names = {d.name for d in self.db.query(models.Dish).all()}
        self.assertEqual(len(names), 144)
        self.assertEqual(names, set(DISH_NAMES_AR))

    def test_fill_sets_all_144_arabic_names(self):
        # The 144-dish Arabic map: every dish in DISH_NAMES_AR must be
        # filled. Dishes from vendors added later (e.g. Alpha-T Grocery)
        # are not in the map and must simply be left alone, not KeyError.
        fill_seed_data(self.db)
        dishes = self.db.query(models.Dish).all()
        named = [d for d in dishes if d.name in DISH_NAMES_AR]
        self.assertEqual(len(named), 144)
        for d in named:
            self.assertEqual(d.name_ar, DISH_NAMES_AR[d.name], d.name)

    def test_fill_is_only_when_empty(self):
        koshary = self.db.query(models.Dish).filter_by(name="Koshary").one()
        koshary.name_ar = "كشري البيت"
        self.db.commit()
        fill_seed_data(self.db)
        self.db.refresh(koshary)
        self.assertEqual(koshary.name_ar, "كشري البيت")  # vendor edit survives
        molokhia = self.db.query(models.Dish).filter_by(name="Molokhia with Chicken").one()
        self.assertEqual(molokhia.name_ar, DISH_NAMES_AR["Molokhia with Chicken"])

    def test_fill_is_idempotent(self):
        fill_seed_data(self.db)
        first = {d.name: d.name_ar for d in self.db.query(models.Dish).all()}
        first_count = self.db.query(models.Dish).count()
        fill_seed_data(self.db)
        fill_seed_data(self.db)
        second = {d.name: d.name_ar for d in self.db.query(models.Dish).all()}
        self.assertEqual(first, second)
        # No hardcoded total: later vendors (e.g. Alpha-T's 149 dishes)
        # legitimately raise the count; idempotency means it stays put.
        self.assertEqual(self.db.query(models.Dish).count(), first_count)


class ArabicNameMigrationTests(unittest.TestCase):
    """Old-shape DB: dishes/order_items WITHOUT the v52 columns gain them
    from ensure_schema; existing rows and data stay intact."""

    def test_ensure_schema_adds_name_ar_columns(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        engine = create_engine(f"sqlite:///{path}")
        try:
            models.Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            db = Session()
            vendor = models.Vendor(name="Legacy Kitchen", fulfillment="pickup")
            db.add(vendor)
            db.flush()
            dish = models.Dish(
                vendor_id=vendor.id, name="Koshary", description="Rice, lentils",
                price=Decimal("9.99"), category="Mains",
            )
            db.add(dish)
            db.flush()
            order = models.Order(
                vendor_id=vendor.id, status="completed", fulfillment="pickup",
                payment_method="cash", subtotal=Decimal("9.99"),
                delivery_fee=Decimal("0"), total=Decimal("9.99"),
            )
            db.add(order)
            db.flush()
            db.add(models.OrderItem(
                order_id=order.id, dish_id=dish.id, dish_name="Koshary",
                unit_price=Decimal("9.99"), quantity=1,
            ))
            db.commit()
            dish_id = dish.id
            db.close()

            # Roll the schema back to its pre-v52 shape.
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE dishes DROP COLUMN name_ar"))
                conn.execute(text("ALTER TABLE order_items DROP COLUMN dish_name_ar"))
            cols = {c["name"] for c in inspect(engine).get_columns("dishes")}
            self.assertNotIn("name_ar", cols)

            with patch.object(database_module, "engine", engine), \
                    patch.object(database_module, "SessionLocal", Session):
                database_module.ensure_schema()
                database_module.ensure_schema()  # second run must be a no-op

            self.assertIn("name_ar", {c["name"] for c in inspect(engine).get_columns("dishes")})
            self.assertIn(
                "dish_name_ar", {c["name"] for c in inspect(engine).get_columns("order_items")}
            )
            db = Session()
            legacy = db.get(models.Dish, dish_id)
            self.assertEqual(legacy.name, "Koshary")
            self.assertIsNone(legacy.name_ar)  # filled later by fill_seed_data
            item = db.query(models.OrderItem).one()
            self.assertEqual(item.dish_name, "Koshary")
            self.assertIsNone(item.dish_name_ar)  # old orders: NULL -> EN fallback
            db.close()
        finally:
            engine.dispose()
            os.unlink(path)


class ArabicSearchAndOrderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.owner = models.User(
            email="owner52@example.com", hashed_password="x", role="vendor", name="Owner"
        )
        self.customer = models.User(
            email="cust52@example.com", hashed_password="x", role="customer", name="Cust"
        )
        self.db.add_all([self.owner, self.customer])
        self.db.flush()
        self.vendor = models.Vendor(
            owner_id=self.owner.id, name="Search Kitchen", fulfillment="pickup"
        )
        self.db.add(self.vendor)
        self.db.flush()
        _seed_menu = [
            ("Koshary", "Rice, lentils, pasta, chickpeas, and spicy tomato sauce"),
            ("Stuffed Grape Leaves", "Grape leaves stuffed with rice and herbs"),
            ("Stuffed Cabbage Rolls", "Cabbage rolls stuffed with rice and beef"),
            ("Molokhia with Chicken", "Molokhia leaves with chicken and garlic"),
        ]
        self.dishes = {}
        for name, desc in _seed_menu:
            d = models.Dish(
                vendor_id=self.vendor.id, name=name, description=desc,
                price=Decimal("9.99"), category="Mains",
                name_ar=DISH_NAMES_AR[name],
            )
            self.db.add(d)
            self.dishes[name] = d
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _list(self, q):
        return dishes_router.list_dishes(
            vendor_id=None, category=None, q=q, featured=None,
            available_only=True, vegetarian=None, vegan=None,
            db=self.db, caller=None,
        )

    def test_search_matches_arabic_name(self):
        # "كشري" appears ONLY in Koshary's name_ar (its description is English).
        hits = self._list("كشري")
        self.assertEqual([d.name for d in hits], ["Koshary"])

    def test_search_matches_mahshi_family(self):
        hits = {d.name for d in self._list("محشي")}
        self.assertIn("Stuffed Grape Leaves", hits)
        self.assertIn("Stuffed Cabbage Rolls", hits)

    def test_dish_out_exposes_name_ar(self):
        out = schemas.DishOut.model_validate(self.dishes["Koshary"])
        self.assertEqual(out.name_ar, "كشري")

    def test_order_snapshots_arabic_name(self):
        import datetime as dt
        from zoneinfo import ZoneInfo

        # _validate_pickup_time interprets naive values as marketplace time;
        # use an explicit Pacific-local noon so CI's UTC clock cannot make
        # this test land outside the vendor's default 10:00–20:00 window.
        pickup_at = (
            dt.datetime.now(ZoneInfo("America/Los_Angeles")) + dt.timedelta(days=1)
        ).replace(hour=12, minute=0, second=0, microsecond=0)
        order = orders_router._prepare_order(
            self.db, self.customer,
            vendor_id=self.vendor.id,
            items=[schemas.OrderItemIn(dish_id=self.dishes["Koshary"].id, quantity=2)],
            fulfillment="pickup",
            pickup_at=pickup_at,
            delivery_address=None,
            payment_method="cash", notes=None, checkout_group=None,
        )
        self.db.add(order)
        self.db.commit()
        item = order.items[0]
        self.assertEqual(item.dish_name, "Koshary")
        self.assertEqual(item.dish_name_ar, "كشري")
        out = schemas.OrderItemOut.model_validate(item)
        self.assertEqual(out.dish_name_ar, "كشري")

    def test_vendor_update_persists_and_clears_name_ar(self):
        dish = self.dishes["Molokhia with Chicken"]
        updated = dishes_router.update_dish(
            dish.id, schemas.DishUpdate(name_ar="ملوخية بيتي"),
            db=self.db, user=self.owner,
        )
        self.assertEqual(updated.name_ar, "ملوخية بيتي")
        cleared = dishes_router.update_dish(
            dish.id, schemas.DishUpdate(name_ar=""),
            db=self.db, user=self.owner,
        )
        self.assertIsNone(cleared.name_ar)

    def test_vendor_create_persists_name_ar(self):
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.52"))
        created = dishes_router.create_dish(
            request, self.vendor.id,
            schemas.DishCreate(name="New Dish", price=Decimal("5.00"), name_ar="طبق جديد"),
            db=self.db, user=self.owner,
        )
        self.assertEqual(created.name_ar, "طبق جديد")
        self.assertEqual(
            self.db.query(models.Dish).filter_by(name="New Dish").one().name_ar, "طبق جديد"
        )


if __name__ == "__main__":
    unittest.main()
