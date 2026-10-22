"""Pydantic v2 request/response schemas."""
from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator, model_validator

PAYMENT_METHODS = ["zelle", "venmo", "cash", "apple_pay", "google_pay", "credit_card"]
FULFILLMENTS = ["pickup", "delivery", "drop"]  # "drop" = community drop batch (Oct 2026)
ORDER_STATUSES = ["new", "preparing", "ready", "on_the_way", "completed", "cancelled"]

# 50 US states as 2-letter codes (for the structured address state dropdown).
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


def _zip_ok(v: str | None) -> str | None:
    """US ZIP: 5 digits, optional -1234 ZIP+4."""
    if v:
        if not re.fullmatch(r"\d{5}(-\d{4})?", v.strip()):
            raise ValueError("ZIP code must be 5 digits (e.g. 98201 or 98201-1234)")
        return v.strip()
    return v


def _state_ok(v: str | None) -> str | None:
    if v:
        code = v.strip().upper()
        if code not in US_STATES:
            raise ValueError("State must be a valid 2-letter US state code")
        return code
    return v


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)  # legacy free-text
    street_address: str | None = Field(default=None, max_length=120)
    apt: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=2)
    zipcode: str | None = Field(default=None, max_length=10)

    @field_validator("state")
    @classmethod
    def _state_valid(cls, v: str | None) -> str | None:
        return _state_ok(v)

    @field_validator("zipcode")
    @classmethod
    def _zip_valid(cls, v: str | None) -> str | None:
        return _zip_ok(v)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)  # legacy free-text
    street_address: str | None = Field(default=None, max_length=120)
    apt: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=2)
    zipcode: str | None = Field(default=None, max_length=10)

    @field_validator("state")
    @classmethod
    def _state_valid(cls, v: str | None) -> str | None:
        return _state_ok(v)

    @field_validator("zipcode")
    @classmethod
    def _zip_valid(cls, v: str | None) -> str | None:
        return _zip_ok(v)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterOut(BaseModel):
    """Signup response. `access_token` is None when the email was already
    registered (no information leak: same shape, no login granted)."""
    access_token: str | None = None
    token_type: str = "bearer"
    registered: bool = True


class UserOut(_Out):
    id: int
    email: str
    name: str
    role: str
    email_verified: bool = False
    is_active: bool = True
    phone: str | None = None
    address: str | None = None  # legacy free-text
    street_address: str | None = None
    apt: str | None = None
    city: str | None = None
    state: str | None = None
    zipcode: str | None = None


# ---------- vendors ----------
class VendorOut(_Out):
    id: int
    name: str
    tagline: str
    area: str
    phone: str
    fulfillment: str
    delivery_fee: Decimal
    # v46: free-delivery threshold (dollars). NULL = off. Delivery orders at
    # or above this items subtotal get the delivery fee waived.
    free_delivery_over: Decimal | None = None
    zelle_handle: str | None = None
    venmo_handle: str | None = None
    street_address: str | None = None
    apt: str | None = None
    city: str | None = None
    state: str | None = None
    zipcode: str | None = None
    avg_rating: float = 0.0
    rating_count: int = 0
    dish_count: int = 0
    # Shop hours (Oct 2026): nullable = always open.
    prep_minutes: int = 30
    open_time: str | None = None  # "HH:MM"
    close_time: str | None = None  # "HH:MM"
    closed_weekdays: str | None = None  # e.g. "5" or "5,6"; 0=Sunday..6=Saturday
    is_paused: bool = False
    # Referral share code (F2, Oct 2026) — unique per vendor, used in /v/<code>.
    referral_code: str | None = None
    # Pickup-point card (F9, Oct 2026) — shown at checkout/confirmation/reminders.
    pickup_address: str | None = None
    pickup_map_url: str | None = None
    pickup_instructions: str | None = None
    # v29 (Oct 2026): delivery zones + chef intro profile. NULL/blank =
    # pickup only / not shown.
    delivery_zips: str | None = None  # comma-separated 5-digit US ZIPs
    intro_video_url: str | None = None  # /img/uploads/videos/*
    chef_name: str | None = None
    chef_photo_url: str | None = None  # /img/uploads/*
    chef_bio: str | None = None
    chef_bio_ar: str | None = None


class EarningsOut(BaseModel):
    vendor_id: int
    total_revenue: Decimal
    order_count: int


# ---------- F2: referral share links (Oct 2026) ----------
class AttributedOrderOut(BaseModel):
    """One order attributed to the vendor via their referral share link."""

    id: int
    created_at: dt.datetime
    subtotal: Decimal
    total: Decimal
    status: str
    rebate: Decimal  # subtotal * referral_rebate_percent / 100 (display only)


class ReferralEarningsOut(BaseModel):
    """Attributed orders + computed rebate for one vendor's shop.

    Display only — no money moves in v1."""

    vendor_id: int
    referral_code: str | None = None
    rebate_percent: Decimal = Decimal("2")
    attributed_orders: list[AttributedOrderOut] = []
    total_rebate: Decimal = Decimal("0")


# ---------- dish modifiers (options) ----------
class DishOptionChoice(BaseModel):
    """One selectable choice in a modifier group, e.g. {"label": "Extra hot", "delta": 1.50}.

    `dish_id` optionally links the choice to one of the vendor's own dishes
    (e.g. a "Sides" choice linked to the vendor's "Steamed Rice" dish) so the
    vendor picks from their menu instead of retyping names. Pricing always
    uses `delta`; the link is organizational only.
    """
    label: str = Field(min_length=1, max_length=40)
    # Family/tray catering needs deltas beyond ±$50 (e.g. Mansaf 6-person +$100);
    # ±500 still catches absurd typos.
    delta: float = Field(ge=-500, le=500)
    dish_id: int | None = Field(default=None, ge=1)

    @field_validator("label")
    @classmethod
    def _label_strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("choice label must not be blank")
        return v


class DishOptionCreate(BaseModel):
    """Create a modifier group for a dish. A dish may have SEVERAL groups.

    selection_type 'single': the customer picks exactly one choice (or none
    when min_select=0). 'multiple': the customer picks between min_select
    and max_select choices (max_select null = unbounded).
    """
    name: str = Field(min_length=1, max_length=80)
    selection_type: str = Field(default="single", max_length=10)
    min_select: int = Field(default=0, ge=0, le=20)
    max_select: int | None = Field(default=None, ge=1, le=20)
    choices: list[DishOptionChoice] = Field(min_length=2, max_length=6)

    @field_validator("name")
    @classmethod
    def _name_strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("option name must not be blank")
        return v

    @model_validator(mode="after")
    def _config_ok(self):
        _validate_option_config(
            self.selection_type, self.min_select, self.max_select, self.choices
        )
        # Normalize: single-choice groups always carry max_select=1.
        if self.selection_type == "single":
            self.max_select = 1
        return self


def _validate_option_config(
    selection_type: str,
    min_select: int,
    max_select: int | None,
    choices: list[DishOptionChoice] | None,
) -> None:
    """Shared create/update validation for a modifier group's configuration."""
    if selection_type not in ("single", "multiple"):
        raise ValueError("selection_type must be 'single' or 'multiple'")
    if min_select < 0:
        raise ValueError("min_select must be >= 0")
    if selection_type == "single":
        if min_select > 1:
            raise ValueError("single-choice groups must have min_select 0 or 1")
        if max_select is not None and max_select != 1:
            raise ValueError("single-choice groups must have max_select 1")
    else:  # multiple
        if max_select is not None and max_select < min_select:
            raise ValueError("max_select must be >= min_select")
    if choices is not None:
        labels = [c.label for c in choices]
        if len(set(labels)) != len(labels):
            raise ValueError("choice labels must be unique within a group")


class DishOptionUpdate(BaseModel):
    """Edit a modifier group. Only the fields sent are changed; the merged
    configuration is validated (e.g. single → max_select must stay 1)."""
    name: str | None = Field(default=None, min_length=1, max_length=80)
    selection_type: str | None = Field(default=None, max_length=10)
    min_select: int | None = Field(default=None, ge=0, le=20)
    max_select: int | None = Field(default=None, ge=1, le=20)
    choices: list[DishOptionChoice] | None = Field(default=None, min_length=2, max_length=6)

    @field_validator("name")
    @classmethod
    def _name_strip(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("option name must not be blank")
        return v


class DishOptionOut(_Out):
    id: int
    dish_id: int
    name: str
    selection_type: str = "single"
    min_select: int = 1
    max_select: int | None = None
    choices: list[DishOptionChoice] = []

    @field_validator("choices", mode="before")
    @classmethod
    def _choices_parse(cls, v):
        # The model stores choices as a JSON TEXT column; parse it for the API.
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (ValueError, TypeError):
                v = []
        return v or []

    @field_validator("selection_type", mode="before")
    @classmethod
    def _seltype_default(cls, v):
        # Rows migrated from older DBs can carry NULL; coerce to 'single'.
        return v or "single"

    @field_validator("min_select", mode="before")
    @classmethod
    def _minsel_default(cls, v):
        return v if v is not None else 1


# ---------- dish ingredients (customizable) ----------
def _ingredient_config_ok(
    name: str | None,
    extra_price: float | None,
    is_allergen: bool | None,
    allergen_name: str | None,
) -> str | None:
    """Shared create/update validation for a dish ingredient. Returns the
    stripped allergen_name (or None)."""
    if name is not None and not name.strip():
        raise ValueError("ingredient name must not be blank")
    if extra_price is not None and not (0 <= extra_price <= 50):
        raise ValueError("extra_price must be between 0 and 50")
    if allergen_name is not None:
        allergen_name = allergen_name.strip() or None
    if is_allergen and not allergen_name:
        raise ValueError("allergen_name is required when is_allergen is true")
    return allergen_name


class DishIngredientCreate(BaseModel):
    """Add a customizable ingredient to a dish.

    included_by_default=True → normally in the dish, removable at checkout
    (when removable=True). False → an add-on the customer may add for
    extra_price.
    """
    name: str = Field(min_length=1, max_length=80)
    included_by_default: bool = True
    removable: bool = True
    extra_price: float = Field(default=0, ge=0, le=50)
    is_vegetarian: bool = False
    is_vegan: bool = False
    is_allergen: bool = False
    allergen_name: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _config_ok(self):
        self.name = self.name.strip()
        self.allergen_name = _ingredient_config_ok(
            self.name, self.extra_price, self.is_allergen, self.allergen_name
        )
        if not self.is_allergen:
            self.allergen_name = None  # don't keep a stale allergen name
        self.extra_price = round(self.extra_price, 2)
        return self


class DishIngredientUpdate(BaseModel):
    """Edit a dish ingredient. Only the fields sent are changed."""
    name: str | None = Field(default=None, min_length=1, max_length=80)
    included_by_default: bool | None = None
    removable: bool | None = None
    extra_price: float | None = Field(default=None, ge=0, le=50)
    is_vegetarian: bool | None = None
    is_vegan: bool | None = None
    is_allergen: bool | None = None
    allergen_name: str | None = Field(default=None, max_length=80)


class DishIngredientOut(_Out):
    id: int
    dish_id: int
    name: str
    included_by_default: bool = True
    removable: bool = True
    extra_price: Decimal = Decimal("0")
    is_vegetarian: bool = False
    is_vegan: bool = False
    is_allergen: bool = False
    allergen_name: str | None = None


# ---------- dishes ----------
class DishOut(_Out):
    id: int
    vendor_id: int
    name: str
    description: str
    price: Decimal
    category: str
    available: bool
    is_featured: bool
    photo_url: str = ""
    discount_percent: int = 0
    avg_rating: float = 0.0
    rating_count: int = 0
    calories: int | None = None
    serving_size: str | None = None
    ingredients: str | None = None
    allergens: str | None = None
    prep_minutes: int | None = None  # NULL = unknown
    stock_quantity: int | None = None  # NULL = unlimited
    is_vegetarian: bool = False
    is_vegan: bool = False
    # Advance ordering (Oct 2026): JSON weekday list 0=Monday..6=Sunday,
    # NULL = every day; cutoff hours NULL = no cutoff.
    available_days: list[int] | None = None
    order_cutoff_hours: int | None = None
    # Grocery barcode (Oct 2026): EAN/UPC from the package; NULL = none.
    barcode: str | None = None
    # Admin moderation hide (Oct 2026): hidden dishes never appear in
    # public browsing; the owning vendor + admin still see them.
    is_hidden: bool = False
    # Low-stock alert threshold (Oct 2026): NULL = default 5 once tracked.
    low_stock_threshold: int | None = None
    options: list[DishOptionOut] = []
    ingredient_options: list[DishIngredientOut] = []  # customizable ingredients
    # Timed flash sale (F7, Oct 2026).
    sale_percent: int | None = None
    sale_start: dt.datetime | None = None
    sale_end: dt.datetime | None = None
    # v29 (Oct 2026): dish video + signature dishes. is_signature is a
    # nullable BOOLEAN in the DB — NULL reads as False here.
    video_url: str | None = None  # /img/uploads/videos/*
    is_signature: bool = False
    signature_rank: int | None = None  # vendor's ordering 1..N; NULL = unordered

    @field_validator("photo_url", mode="before")
    @classmethod
    def _photo_url_default(cls, v):
        # Rows migrated from older DBs can carry NULL photo_url; coerce to "".
        return v or ""

    @field_validator("is_signature", mode="before")
    @classmethod
    def _signature_default(cls, v):
        return bool(v)

    @field_validator("available_days", mode="before")
    @classmethod
    def _days_parse(cls, v):
        # Stored as a JSON TEXT column; NULL/empty/all-7 = every day.
        return _json_list_parse(v, what="optional")

    @field_validator("discount_percent", mode="before")
    @classmethod
    def _discount_default(cls, v):
        # Rows migrated from older DBs can carry NULL discount_percent.
        return v if v is not None else 0

    @computed_field
    @property
    def sale_price(self) -> Decimal:
        """Effective price after discount — the price the customer actually pays.

        Uses the flash-sale-aware discount (F7): while a flash sale is live
        the effective discount is max(standing, flash); otherwise the
        standing discount_percent. Never raises — a bad value falls back to
        the standing discount so one row can't 500 the whole listing.
        """
        try:
            from .flash_sales import effective_discount_percent

            d = effective_discount_percent(self)
        except Exception:  # noqa: BLE001
            d = self.discount_percent or 0
        return round(self.price * (Decimal(1) - Decimal(d) / Decimal(100)), 2)

    @computed_field
    @property
    def sale_active(self) -> bool:
        """Is a flash sale live on this dish right now? (F7)"""
        try:
            from .flash_sales import flash_sale_active

            return bool(flash_sale_active(self))
        except Exception:  # noqa: BLE001
            return False


class DishCreateOut(DishOut):
    """POST /dishes response: the dish + how many past customers the new-dish
    announcement went to (Oct 2026). 0 when there were none to notify."""
    announced_to: int = 0


class AnnouncementOut(BaseModel):
    """One "new from your cooks" announcement for the customer profile feed.

    v40: also carries admin broadcasts. kind="dish" (dish_id/dish_name set)
    or kind="broadcast" (broadcast_id + bilingual title/body set; dish_id=0).
    """
    dish_id: int
    dish_name: str
    vendor_name: str
    created_at: dt.datetime
    unseen: bool
    # v40 broadcast fields (default = dish announcement).
    kind: str = "dish"
    broadcast_id: int | None = None
    title_en: str | None = None
    title_ar: str | None = None
    body_en: str | None = None
    body_ar: str | None = None


# === v40: admin broadcasts ===
class BroadcastIn(BaseModel):
    title_en: str = Field(min_length=1, max_length=200)
    title_ar: str = Field(min_length=1, max_length=200)
    body_en: str = Field(min_length=1, max_length=2000)
    body_ar: str = Field(min_length=1, max_length=2000)
    audience: str = Field(pattern="^(all|vendor)$")
    vendor_id: int | None = None


class BroadcastOut(BaseModel):
    id: int
    title_en: str
    title_ar: str
    body_en: str
    body_ar: str
    audience: str
    vendor_id: int | None = None
    vendor_name: str | None = None
    push_sent: int = 0
    created_at: dt.datetime
# === END v40 ===


def _photo_url_ok(v: str | None) -> str | None:
    """Vendor-supplied photo URLs must be http(s) or a same-site /img/ path (uploads) —
    blocks javascript:/data: schemes."""
    if v:
        low = v.strip().lower()
        if low.startswith("/img/"):
            return v
        if not (low.startswith("https://") or low.startswith("http://")):
            raise ValueError("photo_url must start with http://, https:// or /img/")
    return v


def _delivery_zips_ok(v: str | None) -> str | None:
    """Vendor delivery zones: comma-separated 5-digit US ZIPs.

    Blank/empty normalizes to None (pickup only). Each ZIP must be exactly
    5 digits — anything else is a 422.
    """
    if v is None:
        return None
    parts = [p.strip() for p in str(v).split(",") if p.strip()]
    if not parts:
        return None
    for p in parts:
        if not re.fullmatch(r"[0-9]{5}", p):  # ASCII digits only — \d matches Arabic-Indic etc.
            raise ValueError(f"'{p}' is not a valid 5-digit US ZIP code")
    # Dedup, preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return ",".join(out)


def _delivery_zip_ok(v: str | None) -> str | None:
    """One customer delivery ZIP: blank -> None, else exactly 5 digits."""
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    if not re.fullmatch(r"[0-9]{5}", v):  # ASCII digits only
        raise ValueError("delivery_zip must be a 5-digit US ZIP code")
    return v


def _uploaded_video_url_ok(v: str | None) -> str | None:
    """Dish/vendor video URLs must point at our own video uploads
    (/img/uploads/videos/*) — blank clears the field. Anything else 422s."""
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    if not v.startswith("/img/uploads/videos/"):
        raise ValueError("video must be an uploaded video (/img/uploads/videos/...) or blank")
    return v


def _uploaded_photo_url_ok(v: str | None) -> str | None:
    """Chef photo URLs must be one of our own image uploads (/img/uploads/*) —
    blank clears the field. Video paths (/img/uploads/videos/*) and non-image
    extensions are rejected: use the video field for those. Anything else 422s.
    """
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    if not v.startswith("/img/uploads/"):
        raise ValueError("photo must be an uploaded image (/img/uploads/...) or blank")
    if v.startswith("/img/uploads/videos/"):
        raise ValueError("photo must be an image, not a video — use the video field")
    if not re.search(r"\.(jpe?g|png|webp|gif)$", v.lower()):
        raise ValueError("photo must be an image file (jpg, jpeg, png, webp or gif)")
    return v


def _order_by_date_ok(v: str | None) -> str | None:
    """Holiday order-by cutoff: 'YYYY-MM-DD' and a real calendar date."""
    if v is None:
        return None
    v = str(v).strip()
    if not v:
        return None
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        raise ValueError("order_by must be a real date in YYYY-MM-DD format")
    return v


def _normalize_available_days(v: list[int] | None) -> list[int] | None:
    """Normalize the advance-ordering weekday list: keep valid 0..6 ints,
    sorted and unique; None/empty/the full week all mean "every day" (None).
    Out-of-range entries are dropped."""
    if v is None:
        return None
    days = set()
    for d in v:
        try:
            d = int(d)
        except (TypeError, ValueError):
            continue
        if 0 <= d <= 6:
            days.add(d)
    if not days or len(days) == 7:
        return None
    return sorted(days)


def _normalize_barcode(v: str | None) -> str | None:
    """Barcodes: strip whitespace; blank means "no barcode" (None).
    Kept as a plain string — EAN/UPC are digits, but internal codes can
    carry letters, and leading zeros must survive."""
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _validate_flash_sale(
    sale_percent: int | None,
    sale_start: dt.datetime | None,
    sale_end: dt.datetime | None,
) -> None:
    """F7: a flash sale needs a 1-90 percent AND a real [start, end) window.

    A percent without a window (or a window without a percent) would apply
    forever or never — reject it so the vendor can't create a confusing sale.
    """
    if sale_percent is None:
        if sale_start is not None or sale_end is not None:
            raise ValueError("sale_start/sale_end need a sale_percent")
        return
    if sale_start is None or sale_end is None:
        raise ValueError("a flash sale needs both sale_start and sale_end")
    if sale_start >= sale_end:
        raise ValueError("sale_start must be before sale_end")


# Sale windows are evaluated in America/Los_Angeles (same convention as
# order_windows.py). SQLite drops tzinfo on the datetime round-trip, so an
# aware datetime stored as UTC would come back naive and be misread as LA
# wall time (a 7-hour skew). Normalize to LA wall time (naive) on write —
# what the vendor picked in the portal is what gets evaluated.
def _sale_tz():
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("America/Los_Angeles")
    except Exception:  # noqa: BLE001 — zoneinfo missing (Windows w/o tzdata)
        return dt.timezone(dt.timedelta(hours=-7), name="LA-fallback")


def _sale_dt_to_la(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return value
    if value.tzinfo is None:
        return value  # already naive — assumed LA
    return value.astimezone(_sale_tz()).replace(tzinfo=None)


class DishCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    price: Decimal = Field(ge=0, le=100000)
    category: str = Field(default="Mains", max_length=60)
    photo_url: str = Field(default="", max_length=2000)
    discount_percent: int = Field(default=0, ge=0, le=100)
    calories: int | None = Field(default=None, ge=0, le=10000)
    serving_size: str | None = Field(default=None, max_length=120)
    ingredients: str | None = Field(default=None, max_length=5000)
    allergens: str | None = Field(default=None, max_length=255)
    prep_minutes: int | None = Field(default=None, ge=0, le=1440)
    stock_quantity: int | None = Field(default=None, ge=0, le=1000000)  # NULL = unlimited
    is_vegetarian: bool = False
    is_vegan: bool = False
    # Advance ordering (Oct 2026): weekday ints 0=Monday..6=Sunday; the full
    # week (or []) normalizes to None = every day. Cutoff NULL = no cutoff.
    available_days: list[int] | None = Field(default=None)
    order_cutoff_hours: int | None = Field(default=None, ge=0, le=720)
    barcode: str | None = Field(default=None, max_length=64)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=1000000)
    # Timed flash sale (F7, Oct 2026): percent 1-90 + LA-timezone window.
    sale_percent: int | None = Field(default=None, ge=1, le=90)
    sale_start: dt.datetime | None = None
    sale_end: dt.datetime | None = None

    @field_validator("sale_start", "sale_end")
    @classmethod
    def _sale_dt_la(cls, v: dt.datetime | None) -> dt.datetime | None:
        # Normalize aware datetimes to LA wall time (naive) on write —
        # SQLite drops tzinfo on the round-trip.
        return _sale_dt_to_la(v)

    @model_validator(mode="after")
    def _sale_ok(self):
        _validate_flash_sale(self.sale_percent, self.sale_start, self.sale_end)
        return self

    @field_validator("barcode")
    @classmethod
    def _barcode_normalize(cls, v: str | None) -> str | None:
        return _normalize_barcode(v)

    @field_validator("available_days")
    @classmethod
    def _days_normalize(cls, v: list[int] | None) -> list[int] | None:
        return _normalize_available_days(v)

    @field_validator("price")
    @classmethod
    def _round_price(cls, v: Decimal) -> Decimal:
        return round(v, 2)

    @field_validator("photo_url")
    @classmethod
    def _photo_url_scheme(cls, v: str) -> str:
        return _photo_url_ok(v) or ""


class BulkImportError(BaseModel):
    """One failed CSV row: 1-based spreadsheet row number + machine code."""
    row: int
    code: str  # name_required | price_invalid | price_negative | available_invalid | stock_invalid | dish_invalid
    message: str  # English detail; the vendor portal maps `code` to EN/AR copy


class BulkImportOut(BaseModel):
    created: int
    failed: int
    errors: list[BulkImportError]


class DishUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = Field(default=None, ge=0, le=100000)
    category: str | None = Field(default=None, max_length=60)
    available: bool | None = None
    is_featured: bool | None = None
    photo_url: str | None = Field(default=None, max_length=2000)
    discount_percent: int | None = Field(default=None, ge=0, le=100)
    calories: int | None = Field(default=None, ge=0, le=10000)
    serving_size: str | None = Field(default=None, max_length=120)
    ingredients: str | None = Field(default=None, max_length=5000)
    allergens: str | None = Field(default=None, max_length=255)
    prep_minutes: int | None = Field(default=None, ge=0, le=1440)
    stock_quantity: int | None = Field(default=None, ge=0, le=1000000)  # NULL = unlimited
    is_vegetarian: bool | None = None
    is_vegan: bool | None = None
    available_days: list[int] | None = Field(default=None)
    order_cutoff_hours: int | None = Field(default=None, ge=0, le=720)
    barcode: str | None = Field(default=None, max_length=64)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=1000000)
    # Timed flash sale (F7, Oct 2026): percent 1-90 + LA-timezone window.
    # All three NULL clears the sale. Partial updates merge with the dish's
    # current values — the router validates the merged result (see
    # routers/dishes.py update_dish), so pydantic stays lenient here.
    sale_percent: int | None = Field(default=None, ge=1, le=90)
    sale_start: dt.datetime | None = None
    sale_end: dt.datetime | None = None
    # v29 (Oct 2026): dish video + signature dishes. Max 5 signatures per
    # vendor is enforced in routers/dishes.py (needs a DB count). Rank is
    # 1-based; NULL clears the rank. False unsets the signature flag.
    video_url: str | None = Field(default=None, max_length=2000)
    is_signature: bool | None = None
    signature_rank: int | None = Field(default=None, ge=1, le=1000)

    @field_validator("video_url")
    @classmethod
    def _video_url_valid(cls, v: str | None) -> str | None:
        return _uploaded_video_url_ok(v)

    @field_validator("sale_start", "sale_end")
    @classmethod
    def _sale_dt_la(cls, v: dt.datetime | None) -> dt.datetime | None:
        # Normalize aware datetimes to LA wall time (naive) on write —
        # SQLite drops tzinfo on the round-trip.
        return _sale_dt_to_la(v)

    @field_validator("barcode")
    @classmethod
    def _barcode_normalize(cls, v: str | None) -> str | None:
        return _normalize_barcode(v)

    @field_validator("available_days")
    @classmethod
    def _days_normalize(cls, v: list[int] | None) -> list[int] | None:
        return _normalize_available_days(v)

    @field_validator("photo_url")
    @classmethod
    def _photo_url_scheme(cls, v: str | None) -> str | None:
        return _photo_url_ok(v)


class StockAdjustIn(BaseModel):
    """Relative stock change for the barcode stock-adjust flow.
    Positive = received/restocked, negative = sold/shrunk. Result is
    clamped at 0. A dish with NULL (unlimited) stock: a positive delta
    starts tracking at that value; a negative delta leaves it unlimited."""

    delta: int = Field(ge=-1000000, le=1000000)


class StockMovementOut(_Out):
    """One stock-history row: delta + reason + resulting stock_after."""

    id: int
    dish_id: int
    delta: int
    reason: str
    order_id: int | None = None
    stock_after: int | None = None
    created_at: dt.datetime


class RestockIn(BaseModel):
    """Add `quantity` units to a dish (reason 'restock')."""

    quantity: int = Field(gt=0, le=1000000)


class BulkStockItemIn(BaseModel):
    dish_id: int
    stock_quantity: int | None = Field(default=None, ge=0, le=1000000)


class BulkStockIn(BaseModel):
    vendor_id: int
    items: list[BulkStockItemIn] = Field(min_length=1, max_length=500)


# ---------- admin (Oct 2026: back-office gaps) ----------
class AdminOrderDetailOut(_Out):
    """Admin order detail: the order + its event timeline + its messages."""

    order: OrderOut
    events: list[OrderEventOut] = []
    messages: list[OrderMessageOut] = []


class AdminVendorUpdate(BaseModel):
    is_paused: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    tagline: str | None = Field(default=None, max_length=300)
    area: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    # === v40: per-vendor commission percent (0-100). None = use the global
    # `commission_percent` site setting. ===
    commission_rate: Decimal | None = Field(default=None, ge=0, le=100)


class AdminDishUpdate(BaseModel):
    """Admin dish moderation: hide/unhide (+ available). is_hidden is
    admin-only — the vendor PATCH can never set it."""

    is_hidden: bool | None = None
    available: bool | None = None


class AdminUserOut(_Out):
    id: int
    email: str
    name: str
    role: str
    is_active: bool = True
    phone: str | None = None
    created_at: dt.datetime | None = None


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(customer|vendor|admin|staff)$")
    is_active: bool | None = None


# === v40: staff accounts ===
class AdminUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="staff", pattern="^(customer|vendor|admin|staff)$")
# === END v40 ===


class SiteSettingsOut(BaseModel):
    tax_rate: Decimal = Decimal("0.00")
    commission_percent: Decimal = Decimal("0")
    site_name: str = "Egyptian Home Food Marketplace"
    # F2: referral rebate % (display-only in v1 — no money moves).
    referral_rebate_percent: Decimal = Decimal("2")
    # v40: admin alert toggles + SMS destination + last backup timestamp.
    alert_orders: bool = True
    alert_applications: bool = True
    alert_tickets: bool = True
    alert_phone: str = ""
    last_backup_at: str = ""


class SiteSettingsIn(BaseModel):
    tax_rate: Decimal | None = Field(default=None, ge=0, le=1)
    commission_percent: Decimal | None = Field(default=None, ge=0, le=100)
    site_name: str | None = Field(default=None, min_length=1, max_length=200)
    # F2: referral rebate % (display-only in v1 — no money moves).
    referral_rebate_percent: Decimal | None = Field(default=None, ge=0, le=100)
    # v40: admin alert toggles + SMS destination.
    alert_orders: bool | None = None
    alert_applications: bool | None = None
    alert_tickets: bool | None = None
    alert_phone: str | None = Field(default=None, max_length=40)


class RefundIn(BaseModel):
    """Standalone admin refund: full or partial amount, dollars."""

    amount: Decimal = Field(gt=0, le=100000)


class AuditLogOut(_Out):
    id: int
    admin_user_id: int | None = None
    admin_name: str | None = None
    action: str
    target_type: str | None = None
    target_id: int | None = None
    details: dict | None = None
    created_at: dt.datetime


# ---------- orders ----------
class ModifierIn(BaseModel):
    """One chosen modifier for a line item — validated against the dish's
    option group at checkout (label AND delta must match exactly).

    LEGACY contract (mobile app): prefer `modifiers` for new clients. When
    `modifiers` is absent, this resolves against the dish's single-choice
    group(s).
    """
    choice_label: str = Field(min_length=1, max_length=40)
    delta: float = Field(ge=-500, le=500)


def _name_list_strip(v: list[str] | None, *, max_len: int) -> list[str] | None:
    """Strip ingredient/modifier names; reject blanks and over-long entries."""
    if v is None:
        return None
    out = []
    for s in v:
        s = (s or "").strip()
        if not s:
            raise ValueError("names must not be blank")
        if len(s) > max_len:
            raise ValueError(f"name too long (max {max_len} characters)")
        out.append(s)
    return out


class ModifierChoiceIn(BaseModel):
    """One modifier group's selections in the multi-group contract.

    Labels must match the group's configured choices EXACTLY (case-sensitive);
    price deltas are always taken from the database, never from the client.
    """
    option_id: int
    choice_labels: list[str] = Field(min_length=1, max_length=20)

    @field_validator("choice_labels")
    @classmethod
    def _labels_ok(cls, v: list[str]) -> list[str]:
        return _name_list_strip(v, max_len=40)


class OrderItemIn(BaseModel):
    # === FEATURE 5: exactly ONE of dish_id / bundle_id per line. Bundle
    # lines carry no modifiers or ingredient customization (the bundle's
    # fixed price is the whole story). ===
    dish_id: int | None = None
    bundle_id: int | None = None
    quantity: int = Field(ge=1, le=50)
    modifier: ModifierIn | None = None  # legacy single-group contract (mobile app)
    modifiers: list[ModifierChoiceIn] | None = Field(default=None, max_length=10)
    removed_ingredients: list[str] | None = Field(default=None, max_length=30)
    added_ingredients: list[str] | None = Field(default=None, max_length=30)

    @field_validator("removed_ingredients", "added_ingredients")
    @classmethod
    def _ingredient_names_ok(cls, v: list[str] | None) -> list[str] | None:
        return _name_list_strip(v, max_len=80)

    @model_validator(mode="after")
    def _one_of_dish_or_bundle(self):
        has_dish = self.dish_id is not None
        has_bundle = self.bundle_id is not None
        if has_dish == has_bundle:
            raise ValueError("exactly one of dish_id or bundle_id is required")
        if has_bundle and (
            self.modifier is not None
            or self.modifiers
            or self.removed_ingredients
            or self.added_ingredients
        ):
            raise ValueError("bundle line items cannot be customized")
        return self
    # === END FEATURE 5 ===


class OrderCreate(BaseModel):
    vendor_id: int
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)
    fulfillment: str
    pickup_at: dt.datetime | None = None
    delivery_address: str | None = None
    # v29 (Oct 2026): customer delivery ZIP. Required (5 digits) for
    # delivery orders; the server also checks it against the vendor's
    # delivery_zips zones in routers/orders.py. Ignored for pickup.
    delivery_zip: str | None = Field(default=None, max_length=10)
    payment_method: str
    notes: str | None = Field(default=None, max_length=1000)  # special instructions
    # F2: referral share code the customer came in with. The SERVER resolves
    # it to a real vendor; unknown codes are ignored (never trusted).
    referral_code: str | None = Field(default=None, max_length=12)
    # === FEATURE 8: vendor weekly pickup slot id (pickup only) ===
    pickup_slot_id: int | None = None
    # === END FEATURE 8 ===
    # === Community drops (Oct 2026): batch drop id (fulfillment="drop" only) ===
    drop_id: int | None = None
    # === END community drops ===

    @field_validator("fulfillment")
    @classmethod
    def _fulfillment_ok(cls, v: str) -> str:
        if v not in FULFILLMENTS:
            raise ValueError(f"fulfillment must be one of {FULFILLMENTS}")
        return v

    @model_validator(mode="after")
    def _address_needed_for_delivery(self):
        if self.fulfillment == "delivery" and not (self.delivery_address or "").strip():
            raise ValueError("delivery_address is required for delivery orders")
        return self

    @field_validator("delivery_zip")
    @classmethod
    def _delivery_zip_valid(cls, v: str | None) -> str | None:
        return _delivery_zip_ok(v)

    @field_validator("payment_method")
    @classmethod
    def _payment_ok(cls, v: str) -> str:
        if v not in PAYMENT_METHODS:
            raise ValueError(f"payment_method must be one of {PAYMENT_METHODS}")
        return v


def _json_list_parse(v, *, what: str = "list"):
    """Parse a JSON TEXT column into a Python list (old/NULL rows → default)."""
    if v is None:
        return None if what == "optional" else []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (ValueError, TypeError):
            return [] if what != "optional" else None
    return v or ([] if what != "optional" else None)


class ModifierDetailOut(BaseModel):
    """One group's structured modifier snapshot on an order item."""
    option_id: int
    option_name: str
    labels: list[str] = []
    deltas: list[float] = []


class OrderItemOut(_Out):
    id: int
    dish_id: int | None  # === FEATURE 5: NULL on bundle lines ===
    bundle_id: int | None = None  # === FEATURE 5: bundle line items ===
    dish_name: str
    unit_price: Decimal
    quantity: int
    modifier_label: str | None = None
    # Structured snapshots (JSON TEXT columns parsed for the API).
    modifier_detail: list[ModifierDetailOut] | None = None
    removed_ingredients: list[str] | None = None
    added_ingredients: list[str] | None = None

    @field_validator("modifier_detail", "removed_ingredients", "added_ingredients", mode="before")
    @classmethod
    def _json_parse(cls, v):
        return _json_list_parse(v, what="optional")


class CheckoutGroupIn(BaseModel):
    """One vendor's slice of a multi-vendor checkout. Same field rules as
    OrderCreate; payment_method lives on the parent CheckoutMultiIn (shared)."""
    vendor_id: int
    items: list[OrderItemIn] = Field(min_length=1, max_length=100)
    fulfillment: str
    pickup_at: dt.datetime | None = None
    delivery_address: str | None = None
    # v29 (Oct 2026): customer delivery ZIP — same rules as OrderCreate.
    delivery_zip: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=1000)
    # === FEATURE 8: vendor weekly pickup slot id (pickup only) ===
    pickup_slot_id: int | None = None
    # === END FEATURE 8 ===
    # === Community drops (Oct 2026): drop batch id (fulfillment="drop" only) ===
    drop_id: int | None = None
    # === END community drops ===

    @field_validator("fulfillment")
    @classmethod
    def _fulfillment_ok(cls, v: str) -> str:
        if v not in FULFILLMENTS:
            raise ValueError(f"fulfillment must be one of {FULFILLMENTS}")
        return v

    @field_validator("delivery_zip")
    @classmethod
    def _delivery_zip_valid(cls, v: str | None) -> str | None:
        return _delivery_zip_ok(v)

    @model_validator(mode="after")
    def _address_needed_for_delivery(self):
        if self.fulfillment == "delivery" and not (self.delivery_address or "").strip():
            raise ValueError("delivery_address is required for delivery orders")
        return self


class CheckoutMultiIn(BaseModel):
    """Multi-vendor checkout: one payment, split into one order per vendor."""
    groups: list[CheckoutGroupIn] = Field(min_length=1, max_length=10)
    payment_method: str
    promo_code: str | None = Field(default=None, max_length=40)
    # Loyalty points to redeem (accounts only — guests have no balance).
    # Discount = redeem_points / points_per_dollar_redeem, capped at the
    # order subtotal and at the customer's points balance. <= 0 / None = skip.
    redeem_points: int | None = Field(default=None)
    # F2: referral share code. The SERVER resolves it to a real vendor;
    # unknown codes are ignored (never trusted).
    referral_code: str | None = Field(default=None, max_length=12)

    @field_validator("payment_method")
    @classmethod
    def _payment_ok(cls, v: str) -> str:
        if v not in PAYMENT_METHODS:
            raise ValueError(f"payment_method must be one of {PAYMENT_METHODS}")
        return v

    @model_validator(mode="after")
    def _unique_vendors(self):
        ids = [g.vendor_id for g in self.groups]
        if len(set(ids)) != len(ids):
            raise ValueError("each vendor may appear in only one group")
        return self


# ---------- guest checkout ----------
class GuestInfo(BaseModel):
    """Who is ordering — no account needed."""
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    email: EmailStr | None = None

    @field_validator("name", "phone")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class GuestCheckoutIn(BaseModel):
    """Guest checkout: same groups as checkout_multi, no auth required."""
    guest: GuestInfo
    groups: list[CheckoutGroupIn] = Field(min_length=1, max_length=10)
    payment_method: str
    promo_code: str | None = Field(default=None, max_length=40)
    # F2: referral share code. The SERVER resolves it to a real vendor;
    # unknown codes are ignored (never trusted).
    referral_code: str | None = Field(default=None, max_length=12)

    @field_validator("payment_method")
    @classmethod
    def _payment_ok(cls, v: str) -> str:
        if v not in PAYMENT_METHODS:
            raise ValueError(f"payment_method must be one of {PAYMENT_METHODS}")
        return v

    @model_validator(mode="after")
    def _unique_vendors(self):
        ids = [g.vendor_id for g in self.groups]
        if len(set(ids)) != len(ids):
            raise ValueError("each vendor may appear in only one group")
        return self


class CheckoutMultiOut(BaseModel):
    checkout_group: str
    orders: list["OrderOut"]
    grand_total: Decimal
    points_discount: Decimal = Decimal("0")  # total $ redeemed across sub-orders


class OrderOut(_Out):
    id: int
    customer_id: int | None  # NULL for guest orders
    vendor_id: int
    status: str
    fulfillment: str
    pickup_at: dt.datetime | None
    delivery_address: str | None = None
    payment_method: str
    paid: bool = False
    checkout_group: str | None = None
    promo_code: str | None = None
    discount_amount: Decimal = Decimal("0")
    points_discount: Decimal = Decimal("0")  # $ off from redeemed loyalty points
    subtotal: Decimal
    delivery_fee: Decimal
    tax: Decimal = Decimal("0")
    total: Decimal
    commission_due: Decimal | None = None
    created_at: dt.datetime
    items: list[OrderItemOut] = []
    customer_name: str = ""
    vendor_name: str = ""
    notes: str | None = None
    guest_name: str | None = None
    guest_phone: str | None = None
    # F2: server-validated referral attribution (NULL = none).
    referral_code: str | None = None
    attributed_vendor_id: int | None = None
    # === FEATURE 10: card-payment failure state ('failed' + timestamp) ===
    payment_status: str | None = None
    payment_failed_at: dt.datetime | None = None
    # === END FEATURE 10 ===
    # === FEATURE 8: chosen weekly pickup slot snapshot ===
    pickup_slot_label: str | None = None
    # === END FEATURE 8 ===
    # v29 (Oct 2026): customer delivery ZIP (NULL for pickup orders).
    delivery_zip: str | None = None
    # === Community drops (Oct 2026): the batch drop this order rides in.
    # drop_label is denormalized at creation so it survives drop deletion. ===
    drop_id: int | None = None
    drop_label: str | None = None
    # === v40: cumulative refunded amount (dollars). ===
    refunded_amount: Decimal = Decimal("0")
    # === v41: card brand/last4 for Stripe-paid orders (NULL = no card data).
    # Brand + last4 ONLY — raw card numbers, expiry dates, and CVCs are never
    # stored or returned by this API. ===
    card_brand: str | None = None
    card_last4: str | None = None
    # === v46: delivery photo proof URL (NULL = vendor attached none). ===
    delivery_photo_url: str | None = None


class OrderStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status_ok(cls, v: str) -> str:
        if v not in ORDER_STATUSES:
            raise ValueError(f"status must be one of {ORDER_STATUSES}")
        return v


class OrderEventOut(_Out):
    id: int
    order_id: int
    event_type: str
    message: str
    meta: str = ""
    created_at: dt.datetime


# ---------- community drops (Oct 2026) ----------
def _drop_zips_ok(v: str | None) -> str | None:
    """Drop ZIP coverage: comma-separated 5-digit US ZIPs. At least one is
    required. Normalizes to 'zip1, zip2' form."""
    parts = [p.strip() for p in (v or "").split(",") if p.strip()]
    if not parts:
        raise ValueError("At least one ZIP code is required")
    for p in parts:
        if not (p.isascii() and p.isdigit() and len(p) == 5):
            raise ValueError(f"Invalid ZIP code: {p}")
    return ", ".join(parts)


def _drop_time_ok(v: str | None) -> str | None:
    """Drop window times: 'HH:MM' 24-hour strings."""
    v = (v or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", v):
        raise ValueError("Time must be HH:MM")
    h, m = int(v[:2]), int(v[3:])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Time must be HH:MM")
    return v


class DropIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    address_text: str | None = Field(default=None, max_length=2000)
    zip_codes: str = Field(min_length=1, max_length=2000)
    drop_date: dt.date
    time_start: str = Field(min_length=1, max_length=10)
    time_end: str = Field(min_length=1, max_length=10)
    max_orders: int | None = Field(default=None, ge=1)
    is_active: bool = True

    @field_validator("label", "address_text")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("zip_codes")
    @classmethod
    def _zips_valid(cls, v: str) -> str:
        return _drop_zips_ok(v)

    @field_validator("time_start", "time_end")
    @classmethod
    def _time_valid(cls, v: str) -> str:
        return _drop_time_ok(v)

    @model_validator(mode="after")
    def _window_ok(self):
        if self.time_end <= self.time_start:
            raise ValueError("End time must be after start time")
        return self


class DropUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    address_text: str | None = Field(default=None, max_length=2000)
    zip_codes: str | None = Field(default=None, min_length=1, max_length=2000)
    drop_date: dt.date | None = None
    time_start: str | None = Field(default=None, min_length=1, max_length=10)
    time_end: str | None = Field(default=None, min_length=1, max_length=10)
    max_orders: int | None = Field(default=None, ge=1)
    is_active: bool | None = None

    @field_validator("label", "address_text")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("zip_codes")
    @classmethod
    def _zips_valid(cls, v: str | None) -> str | None:
        return _drop_zips_ok(v) if v is not None else None

    @field_validator("time_start", "time_end")
    @classmethod
    def _time_valid(cls, v: str | None) -> str | None:
        return _drop_time_ok(v) if v is not None else None

    @model_validator(mode="after")
    def _window_ok(self):
        if self.time_start is not None and self.time_end is not None:
            if self.time_end <= self.time_start:
                raise ValueError("End time must be after start time")
        return self


class DropOut(_Out):
    id: int
    vendor_id: int
    label: str
    address_text: str | None = None
    zip_codes: str
    drop_date: dt.date
    time_start: str
    time_end: str
    max_orders: int | None = None
    is_active: bool
    created_at: dt.datetime


# ---------- reviews ----------
class ReviewCreate(BaseModel):
    dish_id: int | None = None
    vendor_id: int
    rating: int = Field(ge=1, le=5)
    text: str | None = Field(default=None, max_length=1000)


class ReviewOut(_Out):
    id: int
    user_id: int
    user_name: str = ""
    dish_id: int | None = None
    vendor_id: int
    rating: int
    text: str | None = None
    vendor_reply: str | None = None
    replied_at: dt.datetime | None = None
    # Customer photo reviews (Oct 2026): JSON TEXT column; NULL = no photos.
    photo_urls: list[str] = []
    # === v40: moderation status — pending | approved | hidden. ===
    status: str = "approved"
    created_at: dt.datetime

    @field_validator("photo_urls", mode="before")
    @classmethod
    def _photos_parse(cls, v):
        return _json_list_parse(v)


class ReviewReplyIn(BaseModel):
    """Vendor reply to a review. Empty/blank text clears the reply."""
    text: str = Field(default="", max_length=2000)


class ReviewStatusUpdate(BaseModel):
    """v40: admin review moderation — approve, hide, or re-pend a review."""
    status: str = Field(pattern="^(pending|approved|hidden)$")


class ReviewListOut(BaseModel):
    reviews: list[ReviewOut]
    avg_rating: float = 0.0
    count: int = 0


# ---------- order messages ----------
class OrderMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def _text_strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v


class OrderMessageOut(_Out):
    id: int
    order_id: int
    sender_role: str
    text: str
    created_at: dt.datetime


# ---------- promo codes ----------
class PromoCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    percent_off: int = Field(ge=1, le=100)
    max_uses: int | None = Field(default=None, ge=1)
    expires_at: dt.datetime | None = None
    active: bool = True

    @field_validator("code")
    @classmethod
    def _code_normalize(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("code must not be blank")
        return v


class PromoCodeUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    percent_off: int | None = Field(default=None, ge=1, le=100)
    max_uses: int | None = Field(default=None, ge=1)
    expires_at: dt.datetime | None = None
    active: bool | None = None

    @field_validator("code")
    @classmethod
    def _code_normalize(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().upper()
        if not v:
            raise ValueError("code must not be blank")
        return v


class PromoCodeOut(_Out):
    id: int
    code: str
    percent_off: int
    max_uses: int | None = None
    used_count: int = 0
    expires_at: dt.datetime | None = None
    active: bool = True
    created_at: dt.datetime


class PromoValidateIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)


class PromoValidateOut(BaseModel):
    valid: bool
    percent_off: int = 0
    reason: str  # "ok" | "not found" | "inactive" | "expired" | "usage limit reached"


# ---------- vendor applications ----------
APPLICATION_STATUSES = ["new", "approved", "declined"]


class VendorApplicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    email: EmailStr
    city: str = Field(min_length=1, max_length=80)
    cooking: str = Field(min_length=1, max_length=255)  # what they cook
    message: str | None = Field(default=None, max_length=2000)
    # WA state permits (Oct 2026). Booleans default False (not held); the route
    # enforces the gate with 400s — never trust the frontend alone.
    permits_food_worker_card: bool = False
    permits_food_worker_card_number: str | None = Field(default=None, max_length=80)
    permits_food_worker_card_expiry: dt.date | None = None
    permits_establishment: bool = False
    permits_establishment_number: str | None = Field(default=None, max_length=80)
    permits_establishment_expiry: dt.date | None = None
    permits_cottage: bool = False
    permits_cottage_number: str | None = Field(default=None, max_length=80)
    permits_cottage_expiry: dt.date | None = None
    permits_business_license: bool = False
    permits_business_license_ubi: str | None = Field(default=None, max_length=80)
    permits_attested: bool = False

    @field_validator("name", "phone", "city", "cooking")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class VendorApplicationOut(_Out):
    id: int
    name: str
    phone: str
    email: str
    city: str
    cooking: str
    message: str | None = None
    status: str
    created_at: dt.datetime
    # WA permits — None = not on file (pre-gate application).
    permits_food_worker_card: bool | None = None
    permits_food_worker_card_number: str | None = None
    permits_food_worker_card_expiry: dt.date | None = None
    permits_establishment: bool | None = None
    permits_establishment_number: str | None = None
    permits_establishment_expiry: dt.date | None = None
    permits_cottage: bool | None = None
    permits_cottage_number: str | None = None
    permits_cottage_expiry: dt.date | None = None
    permits_business_license: bool | None = None
    permits_business_license_ubi: str | None = None
    permits_attested: bool | None = None


class ApplicationStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status_ok(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in APPLICATION_STATUSES:
            raise ValueError(f"status must be one of {APPLICATION_STATUSES}")
        return v


# ---------- favorites ----------
class FavoriteCreate(BaseModel):
    dish_id: int


class FavoriteOut(_Out):
    id: int
    dish_id: int
    created_at: dt.datetime


# ---------- forgot password ----------
class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# ---------- vendor settings ----------
class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    tagline: str | None = Field(default=None, max_length=255)
    area: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    fulfillment: str | None = None
    delivery_fee: Decimal | None = Field(default=None, ge=0, le=100000)
    # v46: free-delivery threshold (dollars). Explicit null clears it
    # (feature off); >= 0 enforced here and in the vendors router.
    free_delivery_over: Decimal | None = Field(default=None, ge=0, le=100000)
    zelle_handle: str | None = Field(default=None, max_length=120)
    venmo_handle: str | None = Field(default=None, max_length=120)
    street_address: str | None = Field(default=None, max_length=120)
    apt: str | None = Field(default=None, max_length=40)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=2)
    zipcode: str | None = Field(default=None, max_length=10)
    # Shop hours + pause switch (Oct 2026).
    prep_minutes: int | None = Field(default=None, ge=0, le=1440)
    open_time: str | None = Field(default=None, max_length=5)  # "HH:MM"
    close_time: str | None = Field(default=None, max_length=5)  # "HH:MM"
    closed_weekdays: str | None = Field(default=None, max_length=20)  # "5" or "5,6"
    is_paused: bool | None = None
    # Pickup-point card (F9, Oct 2026). Empty strings clear the field
    # (normalized to None by the vendors router).
    pickup_address: str | None = Field(default=None, max_length=2000)
    pickup_map_url: str | None = Field(default=None, max_length=500)
    pickup_instructions: str | None = Field(default=None, max_length=2000)
    # v29 (Oct 2026): delivery zones + chef intro profile. delivery_zips is
    # validated + normalized by _delivery_zips_ok (blank -> None = pickup
    # only); video/photo URLs must be our own uploads (blank clears).
    delivery_zips: str | None = Field(default=None, max_length=2000)
    intro_video_url: str | None = Field(default=None, max_length=2000)
    chef_name: str | None = Field(default=None, max_length=120)
    chef_photo_url: str | None = Field(default=None, max_length=2000)
    chef_bio: str | None = Field(default=None, max_length=2000)
    chef_bio_ar: str | None = Field(default=None, max_length=2000)

    @field_validator("pickup_map_url")
    @classmethod
    def _map_url_ok(cls, v: str | None) -> str | None:
        # A map link must be an http(s) URL — blocks javascript:/data: schemes.
        if v:
            v = v.strip()
            low = v.lower()
            if not (low.startswith("https://") or low.startswith("http://")):
                raise ValueError("pickup_map_url must start with http:// or https://")
            return v
        return v

    @field_validator("fulfillment")
    @classmethod
    def _fulfillment_ok(cls, v: str | None) -> str | None:
        if v is not None and v not in ("pickup", "delivery", "both"):
            raise ValueError("fulfillment must be one of pickup, delivery, both")
        return v

    @field_validator("open_time", "close_time")
    @classmethod
    def _hhmm_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError('time must be "HH:MM" (e.g. "09:00")')
        h, m = int(v[:2]), int(v[3:])
        if h > 23 or m > 59:
            raise ValueError('time must be "HH:MM" (e.g. "09:00")')
        return v

    @field_validator("closed_weekdays")
    @classmethod
    def _weekdays_ok(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parts = [p.strip() for p in v.split(",") if p.strip()]
        for p in parts:
            if not p.isdigit() or not 0 <= int(p) <= 6:
                raise ValueError("closed_weekdays must be comma-separated day numbers 0=Sunday..6=Saturday")
        return ",".join(parts) if parts else None

    @field_validator("state")
    @classmethod
    def _state_valid(cls, v: str | None) -> str | None:
        return _state_ok(v)

    @field_validator("zipcode")
    @classmethod
    def _zip_valid(cls, v: str | None) -> str | None:
        return _zip_ok(v)

    @field_validator("delivery_zips")
    @classmethod
    def _delivery_zips_valid(cls, v: str | None) -> str | None:
        return _delivery_zips_ok(v)

    @field_validator("intro_video_url")
    @classmethod
    def _intro_video_valid(cls, v: str | None) -> str | None:
        return _uploaded_video_url_ok(v)

    @field_validator("chef_photo_url")
    @classmethod
    def _chef_photo_valid(cls, v: str | None) -> str | None:
        return _uploaded_photo_url_ok(v)


# ---------- vendor reports ----------
class DayRevenue(BaseModel):
    date: str  # YYYY-MM-DD
    revenue: float = 0.0
    orders: int = 0


class TopDish(BaseModel):
    dish_id: int
    name: str
    qty: int = 0
    revenue: float = 0.0


class ReportSummary(BaseModel):
    per_day: list[DayRevenue]
    by_status: dict[str, int] = {}
    top_dishes: list[TopDish] = []


# ---------- support / complaints ----------
COMPLAINT_CATEGORIES = ["order", "vendor", "payment", "account", "technical", "other"]
COMPLAINT_STATUSES = ["open", "answered", "closed"]


class ComplaintIn(BaseModel):
    category: str = Field(default="other", max_length=20)
    subject: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=5000)
    order_id: int | None = None
    vendor_id: int | None = None

    @field_validator("category")
    @classmethod
    def _category_ok(cls, v: str) -> str:
        v = (v or "other").strip().lower()
        if v not in COMPLAINT_CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(COMPLAINT_CATEGORIES)}")
        return v


class ComplaintOut(_Out):
    id: int
    reporter_id: int
    reporter_name: str | None = None
    reporter_email: str | None = None
    reporter_role: str | None = None
    category: str
    subject: str
    message: str
    order_id: int | None = None
    vendor_id: int | None = None
    vendor_name: str | None = None
    status: str
    admin_reply: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class ComplaintReply(BaseModel):
    admin_reply: str = Field(min_length=1, max_length=5000)
    status: str = Field(default="answered", max_length=20)

    @field_validator("status")
    @classmethod
    def _status_ok(cls, v: str) -> str:
        v = (v or "answered").strip().lower()
        if v not in ("answered", "closed"):
            raise ValueError("status must be 'answered' or 'closed'")
        return v


# ---------- vendor payouts ----------
class PayoutCreate(BaseModel):
    """Admin records an off-system settlement with a vendor (see VendorPayout)."""
    vendor_id: int
    amount: Decimal = Field(gt=0, le=1000000)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("amount")
    @classmethod
    def _round_amount(cls, v: Decimal) -> Decimal:
        return round(v, 2)


class PayoutOut(_Out):
    id: int
    vendor_id: int
    vendor_name: str = ""
    amount: Decimal
    note: str | None = None
    created_at: dt.datetime


# ---------- vendor settlement ledger ----------
SETTLEMENT_SOURCES = ("admin_payout", "direct_customer_payment", "commission_collection")
SETTLEMENT_METHODS = ("cash", "zelle", "venmo", "bank_transfer", "credit_card", "other")


class SettlementCreate(BaseModel):
    vendor_id: int
    order_id: int | None = None
    source: str
    amount: Decimal = Field(gt=0, le=1000000)
    method: str = "other"
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("source")
    @classmethod
    def _source_ok(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if value not in SETTLEMENT_SOURCES:
            raise ValueError("source must be admin_payout, direct_customer_payment, or commission_collection")
        return value

    @field_validator("method")
    @classmethod
    def _method_ok(cls, value: str) -> str:
        value = (value or "other").strip().lower()
        if value not in SETTLEMENT_METHODS:
            raise ValueError("unsupported settlement method")
        return value

    @field_validator("amount")
    @classmethod
    def _settlement_amount_round(cls, value: Decimal) -> Decimal:
        return round(value, 2)


class SettlementOut(_Out):
    id: int
    vendor_id: int
    vendor_name: str = ""
    order_id: int | None = None
    source: str
    amount: Decimal
    method: str
    note: str | None = None
    created_at: dt.datetime


# ---------- loyalty points ----------
class LoyaltyBalanceOut(BaseModel):
    balance: int


class LoyaltyLedgerOut(_Out):
    id: int
    order_id: int | None = None
    delta: int
    reason: str
    note: str | None = None
    created_at: dt.datetime


class LoyaltyRatesOut(BaseModel):
    points_per_dollar: int
    points_per_dollar_redeem: int


class LoyaltyStatsOut(BaseModel):
    total_earned: int
    total_redeemed: int
    total_outstanding: int


class LoyaltyAdjustIn(BaseModel):
    user_id: int
    delta: int
    note: str | None = Field(default=None, max_length=255)

    @field_validator("note")
    @classmethod
    def _note_strip(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class LoyaltySettingsIn(BaseModel):
    points_per_dollar: int | None = Field(default=None)
    points_per_dollar_redeem: int | None = Field(default=None)


# ---------- catering ----------
CATERING_EVENT_TYPES = ["birthday", "wedding", "corporate", "other"]
CATERING_STATUSES = ["new", "contacted", "closed"]


class CateringIn(BaseModel):
    """Public catering inquiry — no auth required."""
    event_type: str
    event_date: dt.date
    location: str = Field(min_length=1, max_length=500)
    contact_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    email: EmailStr | None = None
    food_type: str = Field(min_length=1, max_length=500)
    guest_count: int | None = Field(default=None, ge=1, le=100000)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("event_type")
    @classmethod
    def _event_type_ok(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in CATERING_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {CATERING_EVENT_TYPES}")
        return v

    @field_validator("event_date")
    @classmethod
    def _event_date_ok(cls, v: dt.date) -> dt.date:
        if v < dt.date.today():
            raise ValueError("event_date must not be in the past")
        return v

    @field_validator("location", "contact_name", "phone", "food_type")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class CateringOut(_Out):
    id: int
    event_type: str
    event_date: dt.date
    location: str
    contact_name: str
    phone: str
    email: str | None = None
    food_type: str
    guest_count: int | None = None
    notes: str | None = None
    admin_notes: str | None = None
    status: str
    created_at: dt.datetime


class CateringUpdateIn(BaseModel):
    status: str | None = None
    admin_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def _status_ok(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in CATERING_STATUSES:
            raise ValueError(f"status must be one of {CATERING_STATUSES}")
        return v


# === F3 (Oct 2026): one-tap reorder ===
class FavoriteToggleOut(BaseModel):
    dish_id: int
    favorited: bool  # True = now in favorites, False = removed


# === F4 (Oct 2026): smart bilingual search ===
class SearchHitOut(_Out):
    """One /api/search hit: the dish plus why it matched."""
    dish: DishOut
    score: int = 0  # 3 = exact/normalized substring, 2 = alias/prefix, 1 = fuzzy


class SearchOut(BaseModel):
    query: str
    hits: list[SearchHitOut]


class ZeroResultQueryOut(BaseModel):
    query: str
    count: int  # how many times customers searched for this in the window


# === F6 (Oct 2026): report-a-problem per order ===
PROBLEM_CATEGORIES = ["missing", "wrong_item", "quality", "late"]
PROBLEM_STATUSES = ["new", "in_review", "resolved"]


class OrderProblemCreate(BaseModel):
    order_id: int
    order_item_id: int | None = None
    category: str
    description: str = Field(min_length=1, max_length=2000)
    desired_outcome: str | None = Field(default=None, max_length=1000)

    @field_validator("category")
    @classmethod
    def _category_ok(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in PROBLEM_CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(PROBLEM_CATEGORIES)}")
        return v

    @field_validator("description", "desired_outcome")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class OrderProblemOut(_Out):
    id: int
    order_id: int
    order_item_id: int | None = None
    category: str
    description: str
    photo_url: str | None = None
    desired_outcome: str | None = None
    status: str
    created_at: dt.datetime
    # Enriched (never exposes another customer's data — reporter info only
    # goes to vendor/admin; customers see their own).
    dish_name: str | None = None
    vendor_name: str | None = None
    customer_name: str | None = None


class OrderProblemStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status_ok(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in PROBLEM_STATUSES:
            raise ValueError(f"status must be one of {', '.join(PROBLEM_STATUSES)}")
        return v


# === FEATURE 5: vendor combo meals (family bundles) ===
BUNDLE_MIN_DISHES = 3
BUNDLE_MAX_DISHES = 5


class BundleItemIn(BaseModel):
    dish_id: int
    quantity: int = Field(default=1, ge=1, le=20)


class BundleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    name_ar: str | None = Field(default=None, max_length=160)
    description: str = Field(default="", max_length=2000)
    description_ar: str | None = Field(default=None, max_length=2000)
    price: Decimal = Field(gt=0, le=100000)
    photo_url: str | None = Field(default=None, max_length=2000)
    available: bool = True
    # v29 (Oct 2026): holiday feasts. holiday_name is a display label;
    # order_by is the order-by cutoff date ('YYYY-MM-DD', must be real);
    # max_orders caps the number of orders containing this bundle.
    holiday_name: str | None = Field(default=None, max_length=80)
    order_by: str | None = Field(default=None, max_length=10)
    max_orders: int | None = Field(default=None, ge=1, le=1000000)
    # Count (3–5) is validated in the endpoint -> clean 400, not a 422.
    items: list[BundleItemIn]

    @field_validator("order_by")
    @classmethod
    def _order_by_valid(cls, v: str | None) -> str | None:
        return _order_by_date_ok(v)

    @field_validator("name", "name_ar", "description", "description_ar", "photo_url", "holiday_name", mode="before")
    @classmethod
    def _strip_or_none(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return v or None

    @model_validator(mode="after")
    def _no_dup_dishes(self):
        ids = [i.dish_id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("a dish may appear only once in a bundle")
        return self


class BundleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    name_ar: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    description_ar: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = Field(default=None, gt=0, le=100000)
    photo_url: str | None = Field(default=None, max_length=2000)
    available: bool | None = None
    # v29 (Oct 2026): holiday feasts — same fields as BundleCreate; None =
    # keep the current value.
    holiday_name: str | None = Field(default=None, max_length=80)
    order_by: str | None = Field(default=None, max_length=10)
    max_orders: int | None = Field(default=None, ge=1, le=1000000)
    # Replacing the item list re-validates the 3–5 rule; None = keep items.
    # Count is validated in the endpoint -> clean 400, not a 422.
    items: list[BundleItemIn] | None = None

    @field_validator("order_by")
    @classmethod
    def _order_by_valid(cls, v: str | None) -> str | None:
        return _order_by_date_ok(v)

    @field_validator("name", "name_ar", "description", "description_ar", "photo_url", "holiday_name", mode="before")
    @classmethod
    def _strip_or_none(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return v or None

    @model_validator(mode="after")
    def _no_dup_dishes(self):
        if self.items is not None:
            ids = [i.dish_id for i in self.items]
            if len(set(ids)) != len(ids):
                raise ValueError("a dish may appear only once in a bundle")
        return self


class BundleItemOut(_Out):
    id: int
    dish_id: int
    dish_name: str = ""
    quantity: int


class BundleOut(_Out):
    id: int
    vendor_id: int
    vendor_name: str = ""
    name: str
    name_ar: str | None = None
    description: str = ""
    description_ar: str | None = None
    price: Decimal
    photo_url: str | None = None
    available: bool = True
    items: list[BundleItemOut] = []
    created_at: dt.datetime
    # v29 (Oct 2026): holiday feasts. `ended` is computed server-side (see
    # routers/bundles.py _bundle_ended): order_by < today (LA) OR the
    # max_orders cap is reached OR available=false.
    holiday_name: str | None = None
    order_by: str | None = None
    max_orders: int | None = None
    ended: bool = False
# === END FEATURE 5 ===


# === FEATURE 8: vendor pickup slots ===
_SLOT_HM = re.compile(r"^\d{1,2}:\d{2}$")


def _slot_time_ok(v: str | None) -> str | None:
    """Validate an HH:MM slot time. Returns the normalized "HH:MM" or None."""
    if v is None:
        return None
    v = str(v).strip()
    m = _SLOT_HM.match(v)
    if not m:
        raise ValueError("time must be HH:MM")
    h, mi = int(v.split(":")[0]), int(v.split(":")[1])
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError("time must be a valid HH:MM")
    return f"{h:02d}:{mi:02d}"


WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class PickupSlotCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0=Monday..6=Sunday
    start_time: str
    end_time: str
    active: bool = True

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _times_ok(cls, v):
        return _slot_time_ok(v)

    @model_validator(mode="after")
    def _start_before_end(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        return self


class PickupSlotUpdate(BaseModel):
    weekday: int | None = Field(default=None, ge=0, le=6)
    start_time: str | None = None
    end_time: str | None = None
    active: bool | None = None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _times_ok(cls, v):
        return _slot_time_ok(v)

    @model_validator(mode="after")
    def _start_before_end(self):
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time >= self.end_time
        ):
            raise ValueError("start_time must be before end_time")
        return self


class PickupSlotOut(_Out):
    id: int
    vendor_id: int
    weekday: int
    start_time: str
    end_time: str
    active: bool = True
    label: str = ""  # e.g. "Friday 2:00–6:00 PM"
    next_date: str | None = None  # ISO date of the next occurrence
# === END FEATURE 8 ===


# === SoukBot chat (Gemini-powered, rule-based fallback) ===
class ChatIn(BaseModel):
    message: str = Field(max_length=1000)
    language: str | None = None  # "en" | "ar"; auto-detected when omitted


class ChatOut(BaseModel):
    reply: str | None  # None when source="rule" — client uses its local engine
    source: str  # "ai" | "rule"


# === v29: reorder nudges (Oct 2026) ===
class NudgeOut(BaseModel):
    """One dish the customer ordered in >= 2 past orders whose most recent
    order is >= 21 days ago — a candidate for a reorder nudge."""

    dish_id: int
    dish_name: str
    vendor_id: int
    vendor_name: str
    last_price: Decimal  # unit price of the most recent order line
    photo_url: str = ""
    days_since_last: int
# === END v29 ===
