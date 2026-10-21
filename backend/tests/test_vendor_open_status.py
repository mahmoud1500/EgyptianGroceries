import datetime as dt
import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.routers.vendors import vendor_open_status


class VendorOpenStatusTests(unittest.TestCase):
    def make_vendor(self, **overrides):
        values = {
            "name": "Test Kitchen",
            "is_paused": False,
            "closed_weekdays": None,
            "open_time": None,
            "close_time": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_closed_weekdays_use_sunday_first_values(self):
        # Monday in UTC is still Sunday evening in the marketplace timezone.
        now = dt.datetime(2026, 10, 19, 1, 0, tzinfo=dt.timezone.utc)
        closed, message = vendor_open_status(
            self.make_vendor(closed_weekdays="0"), now=now
        )

        self.assertFalse(closed)
        self.assertIn("closed today", message)

    def test_monday_setting_does_not_close_sunday_evening(self):
        now = dt.datetime(2026, 10, 19, 1, 0, tzinfo=dt.timezone.utc)
        is_open, _ = vendor_open_status(
            self.make_vendor(closed_weekdays="1"), now=now
        )

        self.assertTrue(is_open)

    def test_business_hours_use_pacific_time(self):
        # 20:00 UTC is noon in Pacific Standard Time on this date.
        now = dt.datetime(2026, 1, 19, 20, 0, tzinfo=dt.timezone.utc)
        is_open, message = vendor_open_status(
            self.make_vendor(open_time="09:00", close_time="17:00"), now=now
        )

        self.assertTrue(is_open)
        self.assertIn("closes at 5:00 PM", message)

    def test_naive_test_time_is_treated_as_pacific_time(self):
        now = dt.datetime(2026, 1, 19, 12, 0)
        is_open, _ = vendor_open_status(
            self.make_vendor(open_time="09:00", close_time="17:00"), now=now
        )

        self.assertTrue(is_open)

    def test_paused_vendor_remains_closed(self):
        is_open, message = vendor_open_status(
            self.make_vendor(is_paused=True),
            now=dt.datetime(2026, 1, 19, 20, 0, tzinfo=ZoneInfo("UTC")),
        )

        self.assertFalse(is_open)
        self.assertIn("temporarily paused", message)


if __name__ == "__main__":
    unittest.main()
