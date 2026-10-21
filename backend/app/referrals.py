"""Vendor share links with referral attribution (Oct 2026).

Each vendor gets a unique referral code (e.g. "K7Q2XM9P"). The public
shareable menu link is /v/<code> (redirects to the vendor storefront with
?ref=<code>) or the storefront URL with ?ref=<code> directly.

Checkout accepts an optional `referral_code`; the SERVER validates it maps
to a real vendor and stores referral_code + attributed_vendor_id on the
order — client-side attribution is never trusted. Unknown codes are
ignored (no crash, no attribution).

Rebate: the admin-set `referral_rebate_percent` site setting (default 2).
The vendor portal shows attributed orders + the computed rebate earned —
display only, no money moves in v1.
"""
import secrets
from decimal import Decimal

from sqlalchemy import select

CODE_LEN = 8
# Unambiguous alphabet: no 0/O, 1/I, so codes read cleanly in print/flyers.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_referral_code(db, *, length: int = CODE_LEN) -> str:
    """Generate a referral code not already used by any vendor."""
    from . import models as _m

    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        exists = db.scalar(select(_m.Vendor.id).where(_m.Vendor.referral_code == code))
        if not exists:
            return code


def ensure_referral_codes(db) -> int:
    """Backfill referral codes for vendors that lack one (idempotent).

    Called from seed.py and at app startup. Commits only when it changed
    something.
    """
    from . import models as _m

    vendors = list(
        db.scalars(select(_m.Vendor).where(_m.Vendor.referral_code.is_(None))).all()
    )
    for v in vendors:
        v.referral_code = new_referral_code(db)
    if vendors:
        db.commit()
    return len(vendors)


def resolve_referral(db, code: str | None):
    """Resolve a customer-supplied code to a Vendor, or None.

    Blank/unknown codes return None — the caller ignores them (never
    trusted, never an error).
    """
    if not code:
        return None
    code = str(code).strip().upper()
    if not code:
        return None
    from . import models as _m

    return db.scalar(select(_m.Vendor).where(_m.Vendor.referral_code == code))


def get_rebate_percent(db) -> Decimal:
    """Referral rebate percent (display-only; admin-set via site settings).

    Defaults to 2. Invalid stored values fall back to the default — a bad
    setting must never break the referral earnings view.
    """
    from . import models as _m

    try:
        row = db.scalar(
            select(_m.Setting).where(_m.Setting.key == "referral_rebate_percent")
        )
        if row is not None and (row.value or "").strip() != "":
            pct = Decimal(row.value)
            if Decimal("0") <= pct <= Decimal("100"):
                return pct
    except Exception:  # noqa: BLE001 — fall back to the default
        pass
    return Decimal("2")
