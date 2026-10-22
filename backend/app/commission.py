"""Marketplace commission accounting for direct-to-vendor orders."""
from decimal import Decimal, ROUND_HALF_UP


CENT = Decimal("0.01")

# Payment methods whose money flows straight from the customer to the
# vendor (the checkout code records them the same way: "Cash/Zelle/Venmo
# remain direct-to-vendor methods"). The marketplace never holds these
# funds, so a completed direct-payment order accrues a commission
# RECEIVABLE against the vendor instead of a payout balance.
DIRECT_PAYMENT_METHODS = ("cash", "zelle", "venmo")

# Payment methods the marketplace itself collects (all ride on Stripe).
# The platform holds this money and settles it to the vendor minus
# commission, so these orders feed the payout side of the ledger only —
# they never create receivables.
PLATFORM_PAYMENT_METHODS = ("credit_card", "apple_pay", "google_pay")


def payment_method_key(value) -> str:
    """Normalize a stored payment_method for comparison (legacy rows may
    differ in case/whitespace)."""
    return str(value or "").strip().lower()


def is_direct_payment_method(value) -> bool:
    return payment_method_key(value) in DIRECT_PAYMENT_METHODS


def is_platform_payment_method(value) -> bool:
    return payment_method_key(value) in PLATFORM_PAYMENT_METHODS


def effective_commission_rate(vendor, default_rate: Decimal) -> Decimal:
    """Return the vendor-specific rate or the configured marketplace default."""
    if vendor is not None and vendor.commission_rate is not None:
        return Decimal(str(vendor.commission_rate))
    return Decimal(str(default_rate or 0))


def commission_for_amount(amount, rate: Decimal) -> Decimal:
    """Calculate a commission using money-safe cent rounding."""
    gross = Decimal(str(amount or 0))
    return (gross * Decimal(str(rate or 0)) / Decimal("100")).quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def commission_due_for_order(order, vendor, default_rate: Decimal) -> Decimal:
    """Commission attributable to a completed order, net of proportional refunds.

    New orders use the commission snapshot saved at checkout. Legacy orders
    without a snapshot are calculated with the vendor's current configured rate.
    """
    if order.commission_due is not None:
        due = Decimal(str(order.commission_due or 0))
    else:
        due = commission_for_amount(
            order.total, effective_commission_rate(vendor, default_rate)
        )
    total = Decimal(str(order.total or 0))
    refunded = Decimal(str(getattr(order, "refunded_amount", 0) or 0))
    if total > 0 and refunded > 0:
        remaining = max(Decimal("0"), total - refunded)
        due = (due * remaining / total).quantize(CENT, rounding=ROUND_HALF_UP)
    return max(Decimal("0"), due)
