"""v48: weekly commission statement cycle — "reminders first, auto-pause
if still unpaid" (owner decision, Oct 2026).

Once a week (on the configured weekday) the cycle writes one
CommissionStatement per vendor snapshotting their direct-pay receivable
(cash / Zelle / Venmo commission from commission.py), then applies the
pause state machine when a pause limit is configured. The "warned"
state is LIVE vendor state (Vendor.commission_warned), not history:
every new episode of debt earns its own fresh warning week.

  outstanding > limit, not warned yet -> statement.reminded = True,
                                         commission_warned = True
  outstanding > limit, warned, still unpaid
                                   -> vendor.direct_pay_paused = True
  outstanding <= limit             -> episode closed:
                                      commission_warned = False, and a
                                      paused vendor unpauses (restore)

With no pause limit configured (blank / 0 / unset) the cycle only writes
statements — it never reminds-by-rule, pauses, or restores. Pauses take
effect at checkout (routers/orders.py) and lift immediately when a
recorded commission collection brings the vendor back under the limit
(reevaluate_vendor_pause, called from the settlement endpoint).

Kept OUT of routers/admin.py on purpose: the scheduler (main.py) and the
vendor/admin routers all need it, and admin.py already imports half the
app. The receivable math mirrors routers/admin.py's
_commission_receivable_for_vendor exactly (same filters, same helpers).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import emailer, models
from .commission import CENT, DIRECT_PAYMENT_METHODS, commission_due_for_order

log = logging.getLogger(__name__)

_MARKET_TZ = ZoneInfo("America/Los_Angeles")

PAUSE_LIMIT_KEY = "commission_pause_limit"
WEEKDAY_KEY = "commission_statement_weekday"
LAST_RUN_KEY = "commission_last_run"
DEFAULT_WEEKDAY = 0  # Monday (0=Mon .. 6=Sun, same numbering as date.weekday())


# ---------- settings ----------

def _setting_value(db: Session, key: str) -> str | None:
    row = db.scalar(select(models.Setting).where(models.Setting.key == key))
    return row.value if row is not None else None


def _store_setting(db: Session, key: str, value: str) -> None:
    row = db.scalar(select(models.Setting).where(models.Setting.key == key))
    if row is None:
        db.add(models.Setting(key=key, value=value))
    else:
        row.value = value


def get_pause_limit(db: Session) -> Decimal | None:
    """Configured direct-pay pause limit in dollars. None (blank, 0,
    unset, or corrupt) means the automation NEVER pauses anyone."""
    raw = (_setting_value(db, PAUSE_LIMIT_KEY) or "").strip()
    if not raw:
        return None
    try:
        limit = Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return limit if limit > 0 else None


def get_statement_weekday(db: Session) -> int:
    """Weekday the weekly statements run on: 0=Mon .. 6=Sun (default Mon)."""
    raw = (_setting_value(db, WEEKDAY_KEY) or "").strip()
    try:
        weekday = int(raw)
    except (ValueError, TypeError):
        return DEFAULT_WEEKDAY
    return weekday if 0 <= weekday <= 6 else DEFAULT_WEEKDAY


def get_global_commission_rate(db: Session) -> Decimal:
    """Global commission percent — same source/fallback as
    routers/admin.py's _commission_default (Setting row, else 0)."""
    raw = _setting_value(db, "commission_percent")
    if raw is not None:
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            pass
    return Decimal("0")


# ---------- receivable snapshot ----------

def vendor_receivable(db: Session, vendor: models.Vendor, default_rate: Decimal) -> dict:
    """Decimal-exact receivable figures for one vendor — the same math as
    routers/admin.py's _commission_receivable_for_vendor (completed
    direct-payment orders; outstanding floored at 0)."""
    orders = list(db.scalars(
        select(models.Order).where(
            models.Order.vendor_id == vendor.id,
            models.Order.status == "completed",
            func.lower(func.trim(models.Order.payment_method)).in_(DIRECT_PAYMENT_METHODS),
        )
    ))
    due = sum(
        (commission_due_for_order(o, vendor, default_rate) for o in orders),
        Decimal("0.00"),
    ).quantize(CENT)
    direct_sales = sum(
        (Decimal(str(o.total or 0)) for o in orders), Decimal("0.00")
    ).quantize(CENT)
    collected = Decimal(str(db.scalar(
        select(func.coalesce(func.sum(models.VendorSettlement.amount), 0)).where(
            models.VendorSettlement.vendor_id == vendor.id,
            models.VendorSettlement.source == "commission_collection",
        )
    ) or 0)).quantize(CENT)
    return {
        "direct_order_count": len(orders),
        "direct_sales": direct_sales,
        "commission_due": due,
        "commission_collected": collected,
        "outstanding": max(Decimal("0.00"), due - collected),
    }


# ---------- week helpers ----------

def week_key_and_period(day: dt.date) -> tuple[str, dt.date, dt.date]:
    """ISO week key ("YYYY-Www") + Monday/Sunday bounds for the week
    containing `day`."""
    iso = day.isocalendar()
    start = dt.date.fromisocalendar(iso[0], iso[1], 1)
    return f"{iso[0]}-W{iso[1]:02d}", start, start + dt.timedelta(days=6)


def _as_market_date(now) -> dt.date:
    if now is None:
        return dt.datetime.now(_MARKET_TZ).date()
    if isinstance(now, dt.datetime):
        if now.tzinfo is None:
            return now.date()
        return now.astimezone(_MARKET_TZ).date()
    return now  # already a date


# ---------- the cycle ----------

def run_weekly_statements(db: Session, now=None, *, notify: bool = True) -> dict:
    """Write this week's statement for EVERY vendor and apply the
    remind/pause/restore state machine. Idempotent per (vendor, week):
    a vendor who already has a statement for the current week is skipped
    for statement creation (their restore check still runs).

    Commits on success; rolls back and re-raises on failure (callers —
    scheduler / admin endpoint — contain it) — EXCEPT a lost race
    against a concurrent run (IntegrityError on the unique statement
    key), which returns an empty already-run summary. Vendor
    notification emails are best-effort and sent after the commit.
    """
    today = _as_market_date(now)
    week_key, period_start, period_end = week_key_and_period(today)
    limit = get_pause_limit(db)
    default_rate = get_global_commission_rate(db)
    summary = {
        "week_key": week_key,
        "statements_created": 0,
        "reminded": [],
        "paused": [],
        "unpaused": [],
    }
    pending_emails: list[tuple[str, str, str, str]] = []  # (to, shop, kind, outstanding)
    try:
        vendors = list(db.scalars(select(models.Vendor).order_by(models.Vendor.id)).all())
        for vendor in vendors:
            figures = vendor_receivable(db, vendor, default_rate)
            outstanding = figures["outstanding"]
            existing = db.scalar(
                select(models.CommissionStatement).where(
                    models.CommissionStatement.vendor_id == vendor.id,
                    models.CommissionStatement.week_key == week_key,
                )
            )
            if existing is None:
                stmt = models.CommissionStatement(
                    vendor_id=vendor.id,
                    week_key=week_key,
                    period_start=period_start,
                    period_end=period_end,
                    direct_sales=figures["direct_sales"],
                    commission_due=figures["commission_due"],
                    commission_collected=figures["commission_collected"],
                    outstanding=outstanding,
                )
                if limit is not None and outstanding > limit:
                    if vendor.direct_pay_paused:
                        pass  # already paused: the statement just records figures
                    elif vendor.commission_warned:
                        # Warned for THIS episode in an earlier week and
                        # still over the limit -> pause.
                        vendor.direct_pay_paused = True
                        stmt.pause_applied = True
                        summary["paused"].append(vendor.id)
                        if vendor.owner is not None and vendor.owner.email:
                            pending_emails.append(
                                (vendor.owner.email, vendor.name, "paused", f"{outstanding:.2f}")
                            )
                    else:
                        # First time over the limit for this episode of
                        # debt -> fresh warning week (never an instant
                        # pause, even if old statements show reminders).
                        stmt.reminded = True
                        vendor.commission_warned = True
                        summary["reminded"].append(vendor.id)
                        if vendor.owner is not None and vendor.owner.email:
                            pending_emails.append(
                                (vendor.owner.email, vendor.name, "reminded", f"{outstanding:.2f}")
                            )
                db.add(stmt)
                summary["statements_created"] += 1
            # Episode close: at/under the limit, any open warning episode
            # ends (commission_warned reset, so a FUTURE episode starts
            # with its own warning week) and a paused vendor restores
            # (e.g. a refund shrank the receivable, or the limit was
            # raised). Settlement-driven restores happen immediately in
            # reevaluate_vendor_pause instead.
            if limit is not None and outstanding <= limit:
                vendor.commission_warned = False
                if vendor.direct_pay_paused:
                    vendor.direct_pay_paused = False
                    summary["unpaused"].append(vendor.id)
        _store_setting(db, LAST_RUN_KEY, json.dumps({
            "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            **summary,
        }))
        db.commit()
    except IntegrityError:
        # A concurrent run (a second admin POST, or the scheduler racing
        # one) wrote this week's statements first: the (vendor_id,
        # week_key) unique constraint kept the data clean — no duplicates
        # — so this is an already-completed run, not an error. Roll back
        # and report the already-run state instead of a 500.
        db.rollback()
        log.info("commission cycle: week %s already run by a concurrent caller", week_key)
        return {
            "week_key": week_key,
            "statements_created": 0,
            "reminded": [],
            "paused": [],
            "unpaused": [],
        }
    except Exception:
        db.rollback()
        raise
    if notify:
        for to, shop, kind, outstanding in pending_emails:
            try:
                emailer.send_commission_statement_notice(
                    to, shop,
                    outstanding=outstanding,
                    pause_limit=f"{limit:.2f}" if limit is not None else "0.00",
                    kind=kind,
                    week_key=week_key,
                )
            except Exception as exc:  # noqa: BLE001 — mail must never fail the run
                log.warning("commission %s email to %s failed: %s", kind, to, exc)
    return summary


def maybe_run_due(db: Session, today: dt.date | None = None) -> dict | None:
    """Scheduler entry point: run the weekly cycle iff the configured
    weekday of the current week has arrived AND no statement exists yet
    for the current week (for any vendor). Returns the run summary, or
    None when not due."""
    today = today or dt.datetime.now(_MARKET_TZ).date()
    if today.weekday() < get_statement_weekday(db):
        return None
    week_key, _, _ = week_key_and_period(today)
    already = db.scalar(
        select(models.CommissionStatement.id)
        .where(models.CommissionStatement.week_key == week_key)
        .limit(1)
    )
    if already is not None:
        return None
    return run_weekly_statements(db, now=today)


def reevaluate_vendor_pause(db: Session, vendor: models.Vendor) -> bool:
    """Immediate restore after money moves: if the vendor's CURRENT
    outstanding commission is at/under the pause limit — or no limit is
    configured anymore — lift the pause AND close the warning episode
    (commission_warned reset, so a future episode of debt gets its own
    fresh warning week — the settle event itself ends the episode, no
    intervening weekly run needed). Returns True when any flag changed.
    Does NOT commit (the caller owns the transaction) and never pauses
    anyone — pausing is weekly-only."""
    if not vendor.direct_pay_paused and not vendor.commission_warned:
        return False
    limit = get_pause_limit(db)
    if limit is not None:
        figures = vendor_receivable(db, vendor, get_global_commission_rate(db))
        if figures["outstanding"] > limit:
            return False  # episode still open — flags stay as they are
    changed = False
    if vendor.direct_pay_paused:
        vendor.direct_pay_paused = False
        changed = True
    if vendor.commission_warned:
        vendor.commission_warned = False
        changed = True
    return changed


def last_run_summary(db: Session) -> dict | None:
    """The persisted summary of the most recent cycle run (Setting row)."""
    raw = _setting_value(db, LAST_RUN_KEY)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None
