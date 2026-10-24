"""SQLAlchemy 2.0 models."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")  # customer | vendor | admin
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    address: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)  # legacy free-text; kept, not migrated
    # Structured US address (added Oct 2026; all optional so nobody is blocked).
    street_address: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    apt: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True, default=None)  # 2-letter code
    zipcode: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)
    # Set whenever the password changes; tokens issued before this are rejected.
    password_changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    # Email verification (Oct 2026). Optional: login/checkout never blocked.
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    # Admin deactivation (Oct 2026): False = cannot log in (enforced in
    # auth.get_current_user + the login endpoint). Never deleted — order
    # history keeps pointing at the user. Default True; old rows backfilled.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Loyalty points balance (Oct 2026). Updated in the same transaction as
    # every LoyaltyLedger write; the ledger is the source of truth.
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # "New from your cooks" announcements (Oct 2026): the last time the
    # customer viewed the announcements list; NULL = never (everything is
    # unseen). Nullable by design — old rows keep NULL, no backfill needed.
    last_announcement_seen_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vendors: Mapped[list["Vendor"]] = relationship("Vendor", back_populates="owner")
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="customer")


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # v53 remainder: Arabic vendor name (mirrors Dish.name_ar). NULL = no
    # Arabic name yet; the shop falls back to `name`. Only-when-empty seed
    # fill; vendors can edit it in the portal settings.
    name_ar: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    tagline: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    area: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    fulfillment: Mapped[str] = mapped_column(String(20), nullable=False, default="both")  # pickup | delivery | both
    delivery_fee: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    # Structured shop address (Oct 2026). All optional; legacy `area` stays untouched.
    street_address: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    apt: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True, default=None)
    zipcode: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)
    # Where customers should send Zelle/Venmo payments for this vendor (Oct 2026).
    # Shown in order-confirmation emails and at checkout when relevant.
    zelle_handle: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    venmo_handle: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    # Shop hours (Oct 2026). All nullable = always open. open_time/close_time
    # are "HH:MM" strings; closed_weekdays is e.g. "5" or "5,6" (0=Sunday..6=Saturday).
    prep_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    open_time: Mapped[str | None] = mapped_column(String(5), nullable=True, default=None)
    close_time: Mapped[str | None] = mapped_column(String(5), nullable=True, default=None)
    closed_weekdays: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    # Pause switch (Oct 2026): when True, checkout is blocked with a friendly message.
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Referral share code (F2, Oct 2026): unique 8-char code identifying this
    # vendor in share links (/v/<code> and ?ref=<code>). NULL backfilled at
    # startup by referrals.ensure_referral_codes().
    referral_code: Mapped[str | None] = mapped_column(String(12), nullable=True, unique=True, default=None)
    # Pickup-point card (F9, Oct 2026): where exactly to pick up — shown at
    # checkout (pickup orders), on the order confirmation page, and in
    # status-change emails/pushes. All nullable; an empty card is not shown.
    pickup_address: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    pickup_map_url: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    pickup_instructions: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # === v29: delivery zones + chef intro profile (Oct 2026). All
    # nullable by design: blank/NULL delivery_zips = pickup only; NULL
    # intro/chef fields = simply not shown. No backfill needed. ===
    # Comma-separated 5-digit US ZIPs the vendor delivers to.
    delivery_zips: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    intro_video_url: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    chef_name: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    chef_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    chef_bio: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    chef_bio_ar: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # === END v29 ===
    # === v40: per-vendor commission rate (percent, e.g. 10.0 = 10%).
    # NULL = use the global `commission_percent` site setting. Nullable by
    # design — old rows keep NULL, no backfill needed. ===
    commission_rate: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, default=None)
    # === END v40 ===
    # === v46: free-delivery threshold (dollars). Delivery orders whose
    # items subtotal (before discounts) reaches this amount get delivery_fee
    # waived at order time. NULL = feature off (fee always charged).
    # Nullable by design — old vendors keep NULL, no backfill needed. ===
    free_delivery_over: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, default=None)
    # === END v46 ===
    # === v48: commission automation — direct-pay pause switch. Set by
    # the weekly commission cycle (or an admin override) when the vendor's
    # outstanding direct-pay commission stays over the configured limit;
    # while True, checkout rejects cash/Zelle/Venmo for this shop (card
    # still works). Default False — old vendors are never paused. ===
    direct_pay_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # === v48 fix (Security M1): LIVE "warning issued for the current
    # debt episode" flag. Set when the weekly cycle reminds the vendor;
    # cleared the moment the episode closes (outstanding back at/under
    # the pause limit — at a run, or immediately when a collection is
    # recorded). Every NEW episode of debt therefore gets its own fresh
    # warning week before any pause; deriving "warned" from all past
    # statements paused settled vendors with no warning. Default False. ===
    commission_warned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # === END v48 ===

    owner: Mapped["User | None"] = relationship("User", back_populates="vendors")
    dishes: Mapped[list["Dish"]] = relationship("Dish", back_populates="vendor", cascade="all, delete-orphan")
    # === FEATURE 5/8/10: explicit FK — F2 added a second orders→vendors FK
    # (attributed_vendor_id); without this the Vendor.orders join is ambiguous. ===
    orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="vendor", foreign_keys="Order.vendor_id"
    )
    # === END FEATURE 5/8/10 ===
    payouts: Mapped[list["VendorPayout"]] = relationship(
        "VendorPayout", back_populates="vendor", cascade="all, delete-orphan"
    )
    # === FEATURE 5/8: vendor bundles + weekly pickup slots ===
    bundles: Mapped[list["Bundle"]] = relationship(
        "Bundle", back_populates="vendor", cascade="all, delete-orphan"
    )
    pickup_slots: Mapped[list["PickupSlot"]] = relationship(
        "PickupSlot", back_populates="vendor", cascade="all, delete-orphan"
    )
    # === END FEATURE 5/8 ===


class Dish(Base):
    __tablename__ = "dishes"
    # Stock can never go negative (DBA P0-2): the checkout path uses an
    # atomic conditional UPDATE, and this CHECK is the backstop. NULL =
    # unlimited passes (NULL comparison is not FALSE).
    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_dishes_stock_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # === v52: Arabic dish name (mirrors Bundle.name_ar). NULL = no Arabic
    # name; storefronts fall back to `name` in AR mode. Filled for seeded
    # dishes by fill_seed_data (only-when-empty); vendor-editable. (PR #12
    # introduced this column at String(160); v52 widens it to 200 to match
    # the DishCreate/DishUpdate limit.) ===
    name_ar: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="Mains", index=True)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    photo_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Percent discount applied at checkout: effective price = price * (1 - discount/100).
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Dish detail page info (Oct 2026) — all optional, filled in by vendors.
    calories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    serving_size: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serving_size_ar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ingredients: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingredients_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    allergens: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allergens_ar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Estimated prep time in minutes (Oct 2026); NULL = unknown.
    prep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stock cap (Oct 2026): NULL = unlimited; decremented atomically at checkout.
    stock_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Dietary flags (Oct 2026): vendor-set; filterable on GET /api/dishes.
    is_vegetarian: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_vegan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Advance ordering / weekly specials (Oct 2026). available_days is a JSON
    # list of weekday ints (0=Monday..6=Sunday); NULL = served every day.
    # order_cutoff_hours: customers must order this many hours before the
    # serving day starts; NULL/0 = no cutoff (order until the serving day ends).
    available_days: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    order_cutoff_hours: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Grocery barcode (Oct 2026): EAN/UPC scanned from the package.
    # NULL = no barcode (most cooked dishes). Unique per vendor — enforced
    # by ix_dishes_vendor_barcode + an app-level check in the dishes router.
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    # Admin moderation (Oct 2026): True = hidden from the storefront by the
    # admin (e.g. policy). Separate from `available` (the vendor's own
    # toggle) so a vendor cannot un-hide a moderated dish. Old rows = False.
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Low-stock alert threshold (Oct 2026): NULL = default 5 once stock is
    # tracked; ignored while stock_quantity is NULL (unlimited).
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # Timed flash sale (F7, Oct 2026): sale_percent 1-90 applies ONLY while
    # now is within [sale_start, sale_end] (America/Los_Angeles). NULL
    # percent = no flash sale; an expired window stops applying
    # automatically. When live, the effective discount is
    # max(discount_percent, sale_percent) — see flash_sales.py.
    sale_percent: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    sale_start: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    sale_end: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    # === v29: dish video (Oct 2026). NULL = no video; no backfill needed. ===
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # === END v29 ===
    # === v29: signature dishes (Oct 2026). is_signature marks a vendor's
    # signature dish; NULL is treated as false. signature_rank is the
    # vendor's ordering 1..N; NULL = unordered. Old rows keep NULL —
    # no backfill is needed. ===
    is_signature: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    signature_rank: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # === END v29 ===
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="dishes")
    options: Mapped[list["DishOption"]] = relationship(
        "DishOption", back_populates="dish", cascade="all, delete-orphan"
    )
    dish_ingredients: Mapped[list["DishIngredient"]] = relationship(
        "DishIngredient", back_populates="dish", cascade="all, delete-orphan"
    )


class DishOption(Base):
    """Modifier groups for a dish (e.g. "Spice level", "Sides").

    A dish may have SEVERAL groups (the old one-group-per-dish DB unique
    constraint was dropped in Oct 2026; old databases are migrated).
    selection_type: 'single' (pick exactly one — or none when min_select=0)
    or 'multiple' (pick between min_select and max_select choices;
    max_select NULL = unbounded).
    choices is a JSON list of {"label": str, "delta": float} stored as TEXT.
    """
    __tablename__ = "dish_options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dish_id: Mapped[int] = mapped_column(
        ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    selection_type: Mapped[str] = mapped_column(String(10), nullable=False, default="single")
    min_select: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_select: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    choices: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    dish: Mapped["Dish"] = relationship("Dish", back_populates="options")


class DishIngredient(Base):
    """A customizable ingredient on a dish (Oct 2026).

    included_by_default=True  → the dish normally contains it; the customer
        may remove it at checkout (when removable=True).
    included_by_default=False → an add-on the customer may add for extra_price.
    """
    __tablename__ = "dish_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dish_id: Mapped[int] = mapped_column(
        ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    included_by_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    removable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extra_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    is_vegetarian: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_vegan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_allergen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allergen_name: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    allergen_name_ar: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)

    dish: Mapped["Dish"] = relationship("Dish", back_populates="dish_ingredients")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    # new -> preparing -> ready -> completed   (cancelled any time before completed)
    fulfillment: Mapped[str] = mapped_column(String(20), nullable=False)  # pickup | delivery
    # Pickup appointments are stored as naive UTC datetimes and displayed in
    # the marketplace timezone (America/Los_Angeles).
    pickup_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    # NOTE: payment is only recorded on the order — nothing is actually charged,
    # unless the order was paid through Stripe (paid=True, set by the webhook).
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # special instructions from the customer
    # Links sub-orders created by one multi-vendor checkout (Oct 2026).
    # NULL for orders placed through the legacy single-vendor endpoint.
    checkout_group: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None, index=True)
    subtotal: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    delivery_fee: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    tax: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    # Commission amount captured at checkout so later rate changes do not rewrite history.
    # Nullable for legacy orders; receivable reporting computes a safe fallback.
    commission_due: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, default=None)
    # Promo code applied at checkout (Oct 2026): the code and the per-order
    # discount amount (discount = round(subtotal * pct/100, 2)).
    promo_code: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    # Loyalty points discount applied at checkout (Oct 2026), in dollars.
    # NULL = none (kept nullable so old orders need no backfill).
    points_discount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, default=None)
    # Referral attribution (F2, Oct 2026): SERVER-validated. referral_code
    # is the code the customer came in with; attributed_vendor_id is the
    # vendor it resolved to. Both NULL when no (or a bogus) code was given —
    # bogus codes are ignored, never stored as attribution.
    referral_code: Mapped[str | None] = mapped_column(String(12), nullable=True, default=None)
    attributed_vendor_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id"), nullable=True, default=None
    )
    # Guest checkout (Oct 2026): customer_id is NULL for guest orders.
    # Databases created before the guest-checkout build are migrated to the
    # nullable column automatically by ensure_schema() (_make_customer_id_nullable).
    guest_name: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    guest_phone: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    # === FEATURE 10: payment retry state (Oct 2026). payment_status is set
    # to 'failed' when the Stripe payment-intent/checkout flow errors; the
    # customer may retry within 30 minutes via
    # POST /api/orders/{id}/retry-payment. NULL = no failure recorded. ===
    payment_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    payment_failed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    # === END FEATURE 10 ===
    # === FEATURE 8: chosen weekly pickup slot (Oct 2026). pickup_slot_id is
    # the slot chosen at checkout (NULL when the vendor has no slots);
    # pickup_slot_label is the human snapshot shown on the order, e.g.
    # "Friday 2:00–6:00 PM · Oct 16". ===
    pickup_slot_id: Mapped[int | None] = mapped_column(
        ForeignKey("pickup_slots.id"), nullable=True, default=None
    )
    pickup_slot_label: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # === END FEATURE 8 ===
    # === v29: customer delivery ZIP (Oct 2026). Set when
    # fulfillment=delivery; NULL for pickup orders and for pre-v29 orders
    # (no backfill possible — the old data was never recorded). ===
    delivery_zip: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)
    # === END v29 ===
    # === Community drops (Oct 2026): the drop batch this order rides in
    # (fulfillment='drop'). drop_id is NULL for all other orders. drop_label
    # is a denormalized snapshot of the drop's label so the order still
    # reads correctly if the vendor later deletes the drop. Both nullable;
    # old rows keep NULL — no backfill is needed. Added to old DBs by
    # ensure_schema() (plain ALTER TABLE ADD COLUMN — no rebuild needed). ===
    drop_id: Mapped[int | None] = mapped_column(
        ForeignKey("delivery_drops.id"), nullable=True, default=None, index=True
    )
    drop_label: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    # === END community drops ===
    # === v40: cumulative refunded amount (dollars). Incremented by every
    # successful Stripe refund (standalone admin refund + cancel-path
    # refund); the refund endpoint guards refunded_amount + new <= total
    # for idempotency. Backfilled from successful refund events. ===
    refunded_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    # === END v40 ===
    # === v41: card details from Stripe for orders paid by card. Only the
    # brand (e.g. "visa") and the last 4 digits are stored — NEVER the raw
    # card number, expiry date, or CVC (Stripe's hosted checkout /
    # PaymentSheet keeps full card data; this server only ever sees the
    # brand + last4 from Stripe's API). Both NULL for unpaid orders and for
    # orders paid with a manual method; old rows keep NULL. ===
    card_brand: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    card_last4: Mapped[str | None] = mapped_column(String(4), nullable=True, default=None)
    # === END v41 ===
    # === v46: delivery photo proof — the vendor's handoff photo URL
    # (/img/uploads/*), attached once the order is on_the_way/completed.
    # Shown to the customer on their order page. NULL = no photo. ===
    delivery_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # === END v46 ===
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    customer: Mapped["User | None"] = relationship("User", back_populates="orders")
    # === FEATURE 5/8/10: explicit FK — F2 added a second vendors FK
    # (attributed_vendor_id), so the join is now ambiguous without this. ===
    vendor: Mapped["Vendor"] = relationship(
        "Vendor", back_populates="orders", foreign_keys="Order.vendor_id"
    )
    # === END FEATURE 5/8/10 ===
    # The vendor the order was attributed to via a referral share link
    # (may differ from `vendor`, the vendor that fulfilled it). Explicit
    # foreign_keys so SQLAlchemy doesn't confuse the two Vendor paths.
    attributed_vendor: Mapped["Vendor | None"] = relationship(
        "Vendor", foreign_keys="Order.attributed_vendor_id"
    )
    # === Community drops (Oct 2026): the batch drop this order rides in
    # (NULL for pickup/delivery orders). Explicit foreign_keys so it is
    # never confused with the vendor_id path. ===
    drop: Mapped["DeliveryDrop | None"] = relationship(
        "DeliveryDrop", back_populates="orders", foreign_keys="Order.drop_id"
    )
    # === END community drops ===
    items: Mapped[list["OrderItem"]] = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    events: Mapped[list["OrderEvent"]] = relationship(
        "OrderEvent", back_populates="order", cascade="all, delete-orphan",
        order_by="OrderEvent.created_at",
    )
    messages: Mapped[list["OrderMessage"]] = relationship(
        "OrderMessage", back_populates="order", cascade="all, delete-orphan",
        order_by="OrderMessage.created_at",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    # === FEATURE 5: bundle line items (Oct 2026). Exactly ONE of dish_id /
    # bundle_id is set per line: dish lines price from the dish + modifiers,
    # bundle lines price ONLY from the bundle's fixed price. dish_id became
    # nullable when bundles landed — old databases are migrated by
    # ensure_schema() (_make_order_item_dish_nullable). ===
    dish_id: Mapped[int | None] = mapped_column(ForeignKey("dishes.id"), nullable=True, index=True)
    bundle_id: Mapped[int | None] = mapped_column(
        ForeignKey("bundles.id"), nullable=True, index=True, default=None
    )
    # === END FEATURE 5 ===
    dish_name: Mapped[str] = mapped_column(String(160), nullable=False)  # snapshot at order time
    # === v52: Arabic dish-name snapshot at order time (NULL on bundle lines
    # and on orders placed before v52 — clients fall back to dish_name). ===
    dish_name_ar: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # snapshot at order time
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Modifier snapshot (Oct 2026), e.g. "Spice level: Extra hot (+$1.50)".
    # Widened to TEXT when multi-group modifiers landed (several groups are
    # joined with "; ") — old databases are migrated by ensure_schema().
    modifier_label: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Structured modifier snapshot (Oct 2026): JSON list of
    # {"option_id", "option_name", "labels": [...], "deltas": [...]} —
    # lets clients re-apply a past order's customization exactly (reorder).
    modifier_detail: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Ingredient customization snapshots (Oct 2026): JSON lists of names.
    removed_ingredients: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    added_ingredients: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    order: Mapped["Order"] = relationship("Order", back_populates="items")
    # === FEATURE 5: bundle line items ===
    bundle: Mapped["Bundle | None"] = relationship("Bundle")
    # === END FEATURE 5 ===


class DeliveryJob(Base):
    """Manual-first delivery assignment and delivery-cost ledger for one vendor order."""
    __tablename__ = "delivery_jobs"
    __table_args__ = (
        CheckConstraint(
            "customer_fee >= 0 AND quoted_cost >= 0 AND actual_cost >= 0 AND platform_subsidy >= 0",
            name="ck_delivery_jobs_nonnegative_amounts",
        ),
        UniqueConstraint("order_id", name="uq_delivery_jobs_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="third_party")  # vendor | third_party
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    quoted_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    customer_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    platform_subsidy: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unpaid")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class OrderEvent(Base):
    """Activity log for an order: placed, status changes, emails sent."""
    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # placed | status | email | note | payment | refund
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[str] = mapped_column(Text, nullable=False, default="")  # JSON blob
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    order: Mapped["Order"] = relationship("Order", back_populates="events")


class Review(Base):
    """Customer rating (1-5) + optional text for a dish and/or a vendor."""
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    dish_id: Mapped[int | None] = mapped_column(ForeignKey("dishes.id"), nullable=True, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Vendor reply (Oct 2026): empty text clears the reply.
    vendor_reply: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    replied_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    # Customer photo reviews (Oct 2026): JSON list of up to 3 /img/uploads/*
    # URLs. NULL = no photos (old rows); code treats NULL as [].
    photo_urls: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # === v40: review moderation. pending = awaiting admin approval,
    # approved = visible publicly, hidden = admin-hidden. New reviews enter
    # as pending; existing rows are backfilled to approved. ===
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    # === END v40 ===
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User")
    dish: Mapped["Dish | None"] = relationship("Dish")
    vendor: Mapped["Vendor"] = relationship("Vendor")


class Favorite(Base):
    """Customer's saved dishes."""
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "dish_id", name="uq_favorite_user_dish"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User")
    dish: Mapped["Dish"] = relationship("Dish")


class PasswordResetToken(Base):
    """Single-use password reset tokens (1 hour expiry)."""
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User")


class PushToken(Base):
    """Expo push-notification tokens registered by the mobile app.

    One row per device token (expo_token is UNIQUE). A token can move
    between users (re-login on a shared device), so register upserts by
    expo_token rather than by (user_id, expo_token).
    """
    __tablename__ = "push_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    expo_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)  # ios | android
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User")


class Complaint(Base):
    """Support ticket filed by a customer or vendor; answered by the site admin."""
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    subject: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    admin_reply: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    reporter: Mapped["User"] = relationship("User")


class VendorPayout(Base):
    """Record of an off-system payment to a vendor.

    There is no automated payout flow: the site owner settles with each
    vendor outside the system (Zelle, cash, bank transfer…), then records
    the payment here so there is a single ledger. Vendors can read their
    own payout history; only the admin can create records.
    """
    __tablename__ = "vendor_payouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="payouts")


class VendorSettlement(Base):
    """Auditable money movement for either payment direction.

    source values:
      admin_payout: marketplace paid the vendor
      direct_customer_payment: customer paid the vendor directly
      commission_collection: vendor paid marketplace commission
    """
    __tablename__ = "vendor_settlements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vendor: Mapped["Vendor"] = relationship("Vendor")
    order: Mapped["Order | None"] = relationship("Order")


class CommissionStatement(Base):
    """v48: one weekly commission statement per vendor, written by the
    weekly commission cycle (commission_cycle.run_weekly_statements).

    Figures are a snapshot of the vendor's direct-pay receivable at run
    time. `reminded` marks the warning week (first week over the pause
    limit in the current debt episode); `pause_applied` marks the week the cycle actually paused the
    vendor's direct-pay methods. Unique per (vendor, ISO week) so repeat
    runs in the same week are idempotent.
    """

    __tablename__ = "commission_statements"
    __table_args__ = (
        UniqueConstraint("vendor_id", "week_key", name="uq_commission_statements_vendor_week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    week_key: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # ISO "YYYY-Www"
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    direct_sales: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    commission_due: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    commission_collected: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    outstanding: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    reminded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pause_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vendor: Mapped["Vendor"] = relationship("Vendor")


class PromoCode(Base):
    """Discount code applied at multi-vendor checkout (Oct 2026).

    code is stored UPPERCASE. used_count is incremented once per successful
    checkout_multi, not per sub-order.
    """
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    percent_off: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..100
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class OrderMessage(Base):
    """Chat thread between the customer, the vendor, and the admin about an order."""
    __tablename__ = "order_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)  # customer | vendor | admin
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    order: Mapped["Order"] = relationship("Order", back_populates="messages")


class VendorApplication(Base):
    """Prospective vendor's application form (Oct 2026).

    status: new | approved | declined. Approving creates a Vendor record with
    is_paused=True (invisible/blocked until the admin finishes setup and links
    a login — that step stays manual).
    """
    __tablename__ = "vendor_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(80), nullable=False)
    cooking: Mapped[str] = mapped_column(String(255), nullable=False)  # what they cook
    message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    # WA state permits (Oct 2026). ALL nullable: applications submitted before
    # the permit gate keep NULL here and show as "permits not on file" in the
    # admin inbox — existing vendors are never blocked retroactively.
    # Booleans: True = applicant holds the permit, False = does not, NULL = unknown (pre-gate).
    permits_food_worker_card: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    permits_food_worker_card_number: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    permits_food_worker_card_expiry: Mapped[dt.date | None] = mapped_column(Date, nullable=True, default=None)
    permits_establishment: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    permits_establishment_number: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    permits_establishment_expiry: Mapped[dt.date | None] = mapped_column(Date, nullable=True, default=None)
    permits_cottage: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    permits_cottage_number: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    permits_cottage_expiry: Mapped[dt.date | None] = mapped_column(Date, nullable=True, default=None)
    permits_business_license: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    permits_business_license_ubi: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    permits_attested: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Setting(Base):
    """Site-wide key/value settings (Oct 2026).

    Both key and value are strings; numeric settings are parsed by callers.
    Loyalty rates live here: points_per_dollar, points_per_dollar_redeem.
    """
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class LoyaltyLedger(Base):
    """Append-only ledger of every loyalty-points movement (Oct 2026).

    delta > 0 = earned/adjusted up, delta < 0 = redeemed/adjusted down.
    reason: earn | redeem | adjust. The user's points_balance is updated in
    the SAME transaction as each ledger row — the ledger is the audit trail.
    """
    __tablename__ = "loyalty_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True, default=None
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)  # earn | redeem | adjust
    note: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    user: Mapped["User"] = relationship("User")


class CateringRequest(Base):
    """Catering inquiry from the public catering form (Oct 2026).

    status: new | contacted | closed. The admin works these like an inbox.
    """
    __tablename__ = "catering_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # birthday | wedding | corporate | other
    event_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    contact_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    food_type: Mapped[str] = mapped_column(Text, nullable=False)
    guest_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class StockMovement(Base):
    """Append-only log of every stock change for a dish (Oct 2026).

    delta: signed quantity change (+restock / −sale). reason: sale |
    restock | adjust | cancel_restore. order_id links sale/cancel_restore
    movements to the order that caused them. stock_after is the dish's
    stock_quantity right after this movement (NULL = unlimited).
    The vendor Stock view reads this table as the dish's stock history.
    """
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), nullable=False, index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True, default=None
    )
    stock_after: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    dish: Mapped["Dish"] = relationship("Dish")


class AdminAuditLog(Base):
    """Append-only log of admin back-office actions (Oct 2026).

    Every admin mutation (order status, refund, points adjust, vendor
    pause/edit, dish/review moderation, user role/deactivate, settings)
    writes one row. details is a JSON blob with the before/after values.
    """
    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON blob
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    admin: Mapped["User"] = relationship("User")


# === FEATURE 5: vendor combo meals (family bundles) ===
class Bundle(Base):
    """A vendor's fixed-price combo of 3–5 of their own dishes (Oct 2026).

    At checkout the bundle is priced at its own fixed `price` — the
    component dishes are display-only and never re-priced. A bundle
    belongs to exactly one vendor and rides in that vendor's order group.
    """
    __tablename__ = "bundles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_ar: Mapped[str | None] = mapped_column(String(160), nullable=True, default=None)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # === v29: holiday bundles + order-by cutoff (Oct 2026). All nullable by
    # design — no backfill needed. holiday_name marks a holiday bundle
    # (e.g. "Ramadan", "Eid al-Fitr"); order_by is the order-by cutoff date
    # stored as a plain 'YYYY-MM-DD' string (portable on SQLite+Postgres,
    # lexicographic comparison = chronological); max_orders caps the number
    # of orders, NULL = unlimited. ===
    holiday_name: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    order_by: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)
    max_orders: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    # === END v29 ===
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="bundles")
    items: Mapped[list["BundleItem"]] = relationship(
        "BundleItem", back_populates="bundle", cascade="all, delete-orphan",
        order_by="BundleItem.id",
    )


class BundleItem(Base):
    """One component dish inside a bundle (quantity of that dish)."""
    __tablename__ = "bundle_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bundle_id: Mapped[int] = mapped_column(
        ForeignKey("bundles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    bundle: Mapped["Bundle"] = relationship("Bundle", back_populates="items")
    dish: Mapped["Dish"] = relationship("Dish")
# === END FEATURE 5 ===


# === FEATURE 8: vendor pickup slots ===
class PickupSlot(Base):
    """A vendor's weekly pickup window (Oct 2026).

    weekday: 0=Monday..6=Sunday.
    start_time/end_time are "HH:MM" strings. When a vendor has at least
    one ACTIVE slot, pickup checkout requires the customer to pick one;
    vendors with no slots keep today's behavior (no slot required).
    """
    __tablename__ = "pickup_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="pickup_slots")
# === END FEATURE 8 ===


# === F4 (Oct 2026): smart search zero-result log ===
class SearchQuery(Base):
    """Every search query that returned zero results.

    Read by the vendor portal ("What customers searched for" — a global
    aggregate of the top queries from the last 7 days) so cooks can see
    what dishes customers are looking for and add them to their menus.
    """
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


# === F6 (Oct 2026): report-a-problem per order ===
class OrderProblem(Base):
    """A customer's problem report about a specific order.

    PRIVATE: visible to the order's vendor + the site admin only — never
    public. category in {missing, wrong_item, quality, late};
    status in {new, in_review, resolved}.
    """
    __tablename__ = "order_problems"
    __table_args__ = (
        CheckConstraint(
            "category IN ('missing', 'wrong_item', 'quality', 'late')",
            name="ck_order_problems_category",
        ),
        CheckConstraint(
            "status IN ('new', 'in_review', 'resolved')",
            name="ck_order_problems_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_items.id", ondelete="SET NULL"), nullable=True, index=True, default=None
    )
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Optional photo (uploaded through the shared photo-upload plumbing).
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    desired_outcome: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    order: Mapped["Order"] = relationship("Order")
    customer: Mapped["User"] = relationship("User")


# === New-dish announcements (Oct 2026) ===
class DishAnnouncement(Base):
    """One announcement per dish: created when a vendor publishes a NEW dish.

    dish_id is UNIQUE — editing the dish never re-announces. Customers who
    ordered from the vendor in the past get an Expo push; the website's
    Profile page lists announcements from vendors the customer ordered from.
    """
    __tablename__ = "dish_announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id"), nullable=False, index=True
    )
    dish_id: Mapped[int] = mapped_column(
        ForeignKey("dishes.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    vendor: Mapped["Vendor"] = relationship("Vendor")
    dish: Mapped["Dish"] = relationship("Dish")
# === END new-dish announcements ===


# === Community drops / neighborhood batch delivery (Oct 2026) ===
class DeliveryDrop(Base):
    """A vendor's scheduled neighborhood batch drop-off (Oct 2026).

    The vendor drops all orders at one place/time; customers pick up there.
    zip_codes is a comma-separated list of 5-digit US ZIPs the drop serves.
    drop_date is a plain DATE; time_start/time_end are "HH:MM" strings.
    max_orders NULL = unlimited. Orders ride a drop via orders.drop_id.
    """
    __tablename__ = "delivery_drops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    address_text: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    zip_codes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    drop_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    time_start: Mapped[str] = mapped_column(String(10), nullable=False, default="12:00")
    time_end: Mapped[str] = mapped_column(String(10), nullable=False, default="18:00")
    max_orders: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vendor: Mapped["Vendor"] = relationship("Vendor")
    orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="drop", foreign_keys="Order.drop_id"
    )
# === END community drops ===


# === v40: broadcast announcements (admin -> customers) ===
class Broadcast(Base):
    """One admin broadcast: bilingual message pushed to customers.

    audience: "all" (every customer) or "vendor" (customers who ordered
    from vendor_id). Delivery is Expo push + the in-app announcements
    feed. Rate-limited to 5/day at the endpoint. push_sent records how
    many push tickets were accepted (0 when nobody had the app / tokens).
    """

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    title_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    body_en: Mapped[str] = mapped_column(Text, nullable=False)
    body_ar: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(String(20), nullable=False, default="all")  # all | vendor
    vendor_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id"), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    push_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    vendor: Mapped["Vendor | None"] = relationship("Vendor")
# === END v40 ===
