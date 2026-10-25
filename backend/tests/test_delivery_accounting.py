"""Focused unit tests for delivery subsidy accounting.

These tests do not contact Stripe or any courier provider.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

# Import the backend package in repository test environments.
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app.routers.delivery import _recalculate_subsidy  # noqa: E402


def test_subsidy_is_actual_cost_less_customer_fee():
    job = SimpleNamespace(actual_cost=Decimal("9.00"), customer_fee=Decimal("3.00"), actual_cost_confirmed=True)
    _recalculate_subsidy(job)
    assert job.platform_subsidy == Decimal("6.00")


def test_subsidy_never_goes_below_zero():
    job = SimpleNamespace(actual_cost=Decimal("4.50"), customer_fee=Decimal("5.00"), actual_cost_confirmed=True)
    _recalculate_subsidy(job)
    assert job.platform_subsidy == Decimal("0.00")


def test_subsidy_handles_string_money_values():
    job = SimpleNamespace(actual_cost="12.35", customer_fee="2.10", actual_cost_confirmed=True)
    _recalculate_subsidy(job)
    assert job.platform_subsidy == Decimal("10.25")
