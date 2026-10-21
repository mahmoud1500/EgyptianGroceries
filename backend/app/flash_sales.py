"""Timed flash sales: dish-level sale_percent + a sale window (Oct 2026).

A dish may carry a flash sale: `sale_percent` (1-90) plus `sale_start` /
`sale_end` datetimes. The sale applies ONLY while "now" falls inside
[start, end]; an expired window stops applying automatically — no cleanup
job needed.

Everything is evaluated in America/Los_Angeles (same convention as
order_windows.py), regardless of the server's own timezone. Datetimes
stored by the API carry a UTC offset (ISO from the vendor portal), which
is converted to LA; naive datetimes (legacy rows) are assumed to be LA.

When a flash sale is live, the effective discount is
max(discount_percent, sale_percent) — the standing discount is never made
worse by a flash sale, and an expired flash falls back to the standing
discount (or full price).
"""
import datetime as dt
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")


def _as_la(value: dt.datetime | None) -> dt.datetime | None:
    """Normalize a stored datetime to LA: aware values are converted, naive
    ones are assumed to already be LA."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=LA)
    return value.astimezone(LA)


def flash_sale_active(dish, now: dt.datetime | None = None) -> bool:
    """Is this dish's flash sale live right now?"""
    pct = getattr(dish, "sale_percent", None) or 0
    if pct <= 0:
        return False
    now = now or dt.datetime.now(LA)
    start = _as_la(getattr(dish, "sale_start", None))
    end = _as_la(getattr(dish, "sale_end", None))
    if start is not None and now < start:
        return False
    if end is not None and now > end:
        return False
    return True


def effective_discount_percent(dish, now: dt.datetime | None = None) -> int:
    """Discount the customer actually pays: max(standing, flash when live).

    Old rows (all flash columns NULL) always return the standing
    discount_percent, so existing pricing is unchanged.
    """
    base = getattr(dish, "discount_percent", None) or 0
    if flash_sale_active(dish, now):
        sale = getattr(dish, "sale_percent", None) or 0
        return max(int(base), int(sale))
    return int(base)
