import datetime as dt
import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.emailer import _pickup_time_text
from app.routers.orders import _validate_pickup_time
from app.routers.pickup_slots import slot_next_date


MARKET_TZ = ZoneInfo("America/Los_Angeles")


class PickupScheduleTests(unittest.TestCase):
    def make_vendor(self, **overrides):
        values = {
            "prep_minutes": 30,
            "closed_weekdays": None,
            "open_time": "09:00",
            "close_time": "17:00",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def market_time(self, year, month, day, hour, minute=0):
        return dt.datetime(year, month, day, hour, minute, tzinfo=MARKET_TZ)

    def test_pickup_time_is_normalized_to_utc_for_database(self):
        pickup = dt.datetime(2026, 1, 19, 10, 0, tzinfo=MARKET_TZ)
        stored, slot = _validate_pickup_time(
            self.make_vendor(),
            pickup,
            active_slots=[],
            pickup_slot_id=None,
            now=self.market_time(2026, 1, 19, 9, 0),
        )

        self.assertEqual(stored, dt.datetime(2026, 1, 19, 18, 0))
        self.assertIsNone(slot)

    def test_rejects_pickup_time_before_preparation_lead(self):
        pickup = self.market_time(2026, 1, 19, 9, 20)
        with self.assertRaisesRegex(HTTPException, "preparation"):
            _validate_pickup_time(
                self.make_vendor(),
                pickup,
                active_slots=[],
                pickup_slot_id=None,
                now=self.market_time(2026, 1, 19, 9, 0),
            )

    def test_rejects_pickup_on_vendor_closed_day(self):
        pickup = self.market_time(2026, 1, 20, 10, 0)
        with self.assertRaisesRegex(HTTPException, "closed"):
            _validate_pickup_time(
                self.make_vendor(closed_weekdays="2"),
                pickup,
                active_slots=[],
                pickup_slot_id=None,
                now=self.market_time(2026, 1, 19, 9, 0),
            )

    def test_rejects_pickup_outside_opening_hours(self):
        pickup = self.market_time(2026, 1, 19, 18, 0)
        with self.assertRaisesRegex(HTTPException, "opening hours"):
            _validate_pickup_time(
                self.make_vendor(),
                pickup,
                active_slots=[],
                pickup_slot_id=None,
                now=self.market_time(2026, 1, 19, 9, 0),
            )

    def test_weekly_slot_must_match_next_date_and_start_time(self):
        vendor = self.make_vendor(open_time=None, close_time=None)
        slot = SimpleNamespace(
            id=7,
            weekday=0,
            start_time="12:00",
            end_time="14:00",
            vendor=vendor,
        )
        pickup = self.market_time(2026, 1, 19, 12, 0)
        stored, selected = _validate_pickup_time(
            vendor,
            pickup,
            active_slots=[slot],
            pickup_slot_id=7,
            now=self.market_time(2026, 1, 19, 9, 0),
        )

        self.assertEqual(stored, dt.datetime(2026, 1, 19, 20, 0))
        self.assertIs(selected, slot)

    def test_rejects_time_that_does_not_match_selected_weekly_slot(self):
        vendor = self.make_vendor(open_time=None, close_time=None)
        slot = SimpleNamespace(
            id=7,
            weekday=0,
            start_time="12:00",
            end_time="14:00",
            vendor=vendor,
        )
        with self.assertRaisesRegex(HTTPException, "match the next available"):
            _validate_pickup_time(
                vendor,
                self.market_time(2026, 1, 19, 12, 30),
                active_slots=[slot],
                pickup_slot_id=7,
                now=self.market_time(2026, 1, 19, 9, 0),
            )

    def test_weekly_slot_date_uses_pacific_day_and_skips_elapsed_start(self):
        slot = SimpleNamespace(
            weekday=0,
            start_time="12:00",
            vendor=SimpleNamespace(prep_minutes=30),
        )
        utc_now = dt.datetime(2026, 1, 20, 1, 0, tzinfo=dt.timezone.utc)

        self.assertEqual(
            slot_next_date(slot, now=utc_now),
            dt.date(2026, 1, 26),
        )

    def test_pickup_email_formats_time_in_marketplace_timezone(self):
        utc_time = dt.datetime(2026, 1, 19, 18, 0)

        self.assertIn("10:00 AM PST", _pickup_time_text(utc_time))


if __name__ == "__main__":
    unittest.main()
