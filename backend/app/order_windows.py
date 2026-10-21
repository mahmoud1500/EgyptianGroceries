"""Advance ordering / weekly specials: per-dish order windows (Oct 2026).

A dish may be restricted to certain serving weekdays (`available_days`, a JSON
list of 0=Monday..6=Sunday; NULL = served every day) plus an order cutoff
(`order_cutoff_hours`; NULL/0 = no cutoff). Everything is evaluated in
America/Los_Angeles regardless of the server's own timezone.

Model (deliberately simple — no per-date overrides, no subscriptions):
- D = the next serving date: today when the dish is served every day or today
  is a serving weekday, otherwise the next date whose weekday is served.
- cutoff(D):
  - day-restricted dish with a cutoff: LA midnight at the START of D minus
    order_cutoff_hours (e.g. Friday serving day + 4h -> order by Thu 8:00 PM).
  - day-restricted dish without a cutoff: end of D (order any time through
    the serving day, or in advance for a later serving day).
  - every-day dish: end of TODAY minus order_cutoff_hours — a same-day
    deadline (e.g. 4h -> order by 8:00 PM today). Start-of-day anchoring would
    leave the window permanently closed for daily dishes, so daily dishes use
    the same-day deadline instead.
- Ordering for D is open while now <= cutoff(D). Once the cutoff passes,
  ordering stays closed until the serving day ends (LA midnight after D),
  when the window for the next serving day opens.
"""
import datetime as dt
import json
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]

_DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def parse_available_days(raw) -> list[int] | None:
    """JSON TEXT column -> sorted weekday ints (0=Monday..6=Sunday).

    Returns None (= every day) for NULL, unparseable, empty, or all-7 lists.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    days: set[int] = set()
    for d in raw or []:
        try:
            d = int(d)
        except (TypeError, ValueError):
            continue
        if 0 <= d <= 6:
            days.add(d)
    if not days or len(days) == 7:
        return None
    return sorted(days)


def _la_midnight(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, tzinfo=LA)


def dish_order_window(dish, now: dt.datetime | None = None) -> dict:
    """Is this dish orderable right now? Returns a status dict.

    Keys: open, restricted, days (restriction or None), has_cutoff,
    serving_date (date), cutoff (LA datetime), opens_at (LA datetime — when
    ordering reopens if currently closed).
    """
    days = parse_available_days(getattr(dish, "available_days", None))
    cutoff_hours = getattr(dish, "order_cutoff_hours", None) or 0
    now = now or dt.datetime.now(LA)
    now = now.replace(tzinfo=LA) if now.tzinfo is None else now.astimezone(LA)
    today = now.date()

    if days is None:
        # Served every day: same-day deadline.
        serving = today
        midnight = _la_midnight(serving)
        cutoff = midnight + dt.timedelta(days=1) - dt.timedelta(hours=cutoff_hours)
    else:
        serving = None
        for k in range(8):
            cand = today + dt.timedelta(days=k)
            if cand.weekday() in days:
                serving = cand
                break
        if serving is None:  # degenerate (can't happen — days is non-empty)
            return {
                "open": False,
                "restricted": True,
                "days": days,
                "has_cutoff": cutoff_hours > 0,
                "serving_date": today,
                "cutoff": now,
                "opens_at": _la_midnight(today) + dt.timedelta(days=1),
            }
        midnight = _la_midnight(serving)
        if cutoff_hours > 0:
            cutoff = midnight - dt.timedelta(hours=cutoff_hours)
        else:
            cutoff = midnight + dt.timedelta(days=1)
    return {
        "open": now <= cutoff,
        "restricted": days is not None or cutoff_hours > 0,
        "days": days,
        "has_cutoff": cutoff_hours > 0,
        "serving_date": serving,
        "cutoff": cutoff,
        "opens_at": midnight + dt.timedelta(days=1),
    }


def _days_phrase(days: list[int] | None) -> str:
    if days is None:
        return "daily"
    return ", ".join(_DAY_NAMES[d] + "s" for d in days)


def _fmt_cutoff(cutoff: dt.datetime) -> str:
    # "Thu 8:00 PM" in America/Los_Angeles.
    return cutoff.strftime("%a %I:%M %p").replace(" 0", " ")


def order_window_block_message(dish_name: str, info: dict | None = None, dish=None) -> str:
    """Friendly 400 detail for a closed order window (English, like the other
    server-side checkout messages — the customer frontend pre-blocks with a
    localized message before this is ever reached)."""
    if info is None:
        info = dish_order_window(dish)
    name = dish_name or "This dish"
    return (
        f"'{name}' is available {_days_phrase(info['days'])} — "
        f"order by {_fmt_cutoff(info['cutoff'])} "
        f"for {_DAY_NAMES[info['serving_date'].weekday()]}. "
        f"Ordering opens {_DAY_NAMES[info['opens_at'].weekday()]}."
    )
