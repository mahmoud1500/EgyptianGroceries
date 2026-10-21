"""Database engine + session wiring. Tables are created with
SQLAlchemy create_all on startup (no Alembic for this test build)."""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# No default credential (DBA P0-4): if DATABASE_URL is unset the app
# refuses to start instead of silently connecting to localhost with a
# publicly documented username/password. Dev sets
# DATABASE_URL=sqlite:///./app.db (see backend/.env.example); prod sets
# its Postgres URL.
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set — refusing to start with a default credential. "
        "Set it to your Postgres URL (prod) or 'sqlite:///./app.db' (local dev). "
        "See backend/.env.example."
    )


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, pool_pre_ping=True)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    """Enforce foreign keys on SQLite (off by default) so dev fails the
    same way prod Postgres does (DBA P0-3). Without this, dev silently
    orphans favorites/reviews on dish delete while prod 500s."""
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema():
    """Add columns to existing tables when the models gain new fields.

    create_all() only creates missing tables, so without this, databases
    created by an older build would be missing new columns.
    Works on both SQLite and PostgreSQL.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "orders" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("orders")}
        with engine.begin() as conn:
            if "delivery_address" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_address TEXT"))
            if "notes" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN notes TEXT"))
            if "paid" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN paid BOOLEAN DEFAULT FALSE"))
            # Multi-vendor checkout link (Oct 2026). Nullable; old orders keep NULL.
            if "checkout_group" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN checkout_group VARCHAR(36)"))
            # Itemized tax (Oct 2026). Old orders keep 0 via the column default.
            if "tax" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN tax NUMERIC(10, 2) DEFAULT 0"))
            # Promo code + discount (Oct 2026). Nullable; old orders keep NULL/0.
            if "promo_code" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN promo_code VARCHAR(40)"))
            if "discount_amount" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN discount_amount NUMERIC(10, 2) DEFAULT 0"))
            conn.execute(text("UPDATE orders SET discount_amount = 0 WHERE discount_amount IS NULL"))
            # Guest checkout (Oct 2026). Nullable; authenticated orders keep NULL.
            if "guest_name" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN guest_name VARCHAR(120)"))
            if "guest_phone" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN guest_phone VARCHAR(40)"))
            # Loyalty points discount, in dollars (Oct 2026). Nullable — NULL
            # means no points were redeemed; old orders keep NULL.
            if "points_discount" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN points_discount NUMERIC(10, 2)"))
            # Referral attribution (F2, Oct 2026). Nullable — NULL = no
            # attribution; old orders keep NULL, so no backfill is needed.
            if "referral_code" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN referral_code VARCHAR(12)"))
            if "attributed_vendor_id" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN attributed_vendor_id INTEGER"))
            # === FEATURE 10: payment retry state (Oct 2026). Both nullable;
            # old orders keep NULL = no failure recorded. ===
            if "payment_status" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN payment_status VARCHAR(20)"))
            if "payment_failed_at" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN payment_failed_at TIMESTAMP"))
            # === END FEATURE 10 ===
            # === FEATURE 8: chosen weekly pickup slot (Oct 2026). Both
            # nullable; old orders keep NULL = no slot chosen. ===
            if "pickup_slot_id" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN pickup_slot_id INTEGER"))
            if "pickup_slot_label" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN pickup_slot_label TEXT"))
            # === END FEATURE 8 ===
            # === v29: customer delivery ZIP (Oct 2026). NULL for pickup
            # orders and for pre-v29 delivery orders (the old data was never
            # recorded, so no backfill is possible). ===
            if "delivery_zip" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_zip VARCHAR(10)"))
            # === END v29 ===
            # === Community drops (Oct 2026): drop_id FK + denormalized
            # drop_label. Both nullable; old orders keep NULL = not a drop
            # order, so no backfill is needed. ===
            if "drop_id" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN drop_id INTEGER"))
            if "drop_label" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN drop_label VARCHAR(120)"))
            # === v40: cumulative refunded amount (dollars). Old orders keep
            # 0 here; historical successful refunds are summed from the event
            # log by _backfill_refunded_amount() below. ===
            if "refunded_amount" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN refunded_amount NUMERIC(10, 2) DEFAULT 0"))
            conn.execute(text("UPDATE orders SET refunded_amount = 0 WHERE refunded_amount IS NULL"))
            # === END v40 ===
            # === v41: card brand/last4 for Stripe-paid orders. Both nullable;
            # old rows keep NULL = no card data. Raw PAN/expiry/CVC are never
            # stored — only what Stripe's API returns (brand + last4). ===
            if "card_brand" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN card_brand VARCHAR(20)"))
            if "card_last4" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN card_last4 VARCHAR(4)"))
            # === END v41 ===
            # === v46: delivery photo proof URL. Nullable; old orders keep
            # NULL = no photo, so no backfill is needed. ===
            if "delivery_photo_url" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN delivery_photo_url TEXT"))
            # === END v46 ===
            # === END community drops ===
            # Guest checkout (Oct 2026) needs customer_id NULLABLE. Databases
            # created before the guest-checkout build still have NOT NULL —
            # migrate them here (P1-2, 2026-10-15 audit). Fresh DBs get the
            # nullable column from create_all(); the helper no-ops there.
        # Runs AFTER this block's ALTERs commit, on its own connection
        # (its SQLite table rebuild needs FK enforcement OFF — see the
        # helper), so it is called outside the `with engine.begin()`.
        _make_customer_id_nullable()
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            if "phone" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(40)"))
            if "address" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN address TEXT"))
            if "password_changed_at" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP"))
            # Structured address fields (Oct 2026). Legacy `address` stays untouched.
            if "street_address" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN street_address VARCHAR(120)"))
            if "apt" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN apt VARCHAR(40)"))
            if "city" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN city VARCHAR(80)"))
            if "state" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN state VARCHAR(2)"))
            if "zipcode" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN zipcode VARCHAR(10)"))
            # Email verification (Oct 2026). Optional — login/checkout never blocked.
            if "email_verified" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE users SET email_verified = FALSE WHERE email_verified IS NULL"))
            if "verification_token" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN verification_token VARCHAR(64)"))
            # Loyalty points balance (Oct 2026). Old users start at 0.
            if "points_balance" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN points_balance INTEGER DEFAULT 0"))
            conn.execute(text("UPDATE users SET points_balance = 0 WHERE points_balance IS NULL"))
            # Admin deactivation (Oct 2026). Old users stay active.
            if "is_active" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
            conn.execute(text("UPDATE users SET is_active = TRUE WHERE is_active IS NULL"))
            # === New-dish announcements (Oct 2026): last time the customer
            # viewed the announcements list. Nullable by design — NULL =
            # never viewed, so no backfill is needed. ===
            if "last_announcement_seen_at" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN last_announcement_seen_at TIMESTAMP"))
            # === END new-dish announcements ===
    if "dishes" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("dishes")}
        with engine.begin() as conn:
            if "photo_url" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN photo_url TEXT"))
            # Older rows migrated before photo_url existed carry NULL; backfill.
            conn.execute(text("UPDATE dishes SET photo_url = '' WHERE photo_url IS NULL"))
            if "discount_percent" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN discount_percent INTEGER DEFAULT 0"))
            conn.execute(text("UPDATE dishes SET discount_percent = 0 WHERE discount_percent IS NULL"))
            # Dish detail page fields (Oct 2026) — nullable by design, no backfill needed.
            if "calories" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN calories INTEGER"))
            if "serving_size" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN serving_size VARCHAR(120)"))
            if "ingredients" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN ingredients TEXT"))
            if "allergens" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN allergens VARCHAR(255)"))
            # Stock cap (Oct 2026) — NULL = unlimited, no backfill needed.
            if "stock_quantity" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN stock_quantity INTEGER"))
            # Dietary flags (Oct 2026). Old dishes are neither until the vendor says so.
            if "is_vegetarian" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN is_vegetarian BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE dishes SET is_vegetarian = FALSE WHERE is_vegetarian IS NULL"))
            if "is_vegan" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN is_vegan BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE dishes SET is_vegan = FALSE WHERE is_vegan IS NULL"))
            # Advance ordering / weekly specials (Oct 2026). Both nullable by
            # design: NULL available_days = every day, NULL order_cutoff_hours
            # = no cutoff. Old rows keep NULL — the code treats NULL as "no
            # restriction", so no backfill UPDATE is needed.
            if "available_days" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN available_days TEXT"))
            if "order_cutoff_hours" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN order_cutoff_hours INTEGER"))
            # Grocery barcode (Oct 2026) — NULL for dishes without one; no
            # backfill needed, existing rows keep NULL = "no barcode".
            if "barcode" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN barcode VARCHAR(64)"))
            # Admin moderation hide (Oct 2026). Old dishes are visible.
            if "is_hidden" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN is_hidden BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE dishes SET is_hidden = FALSE WHERE is_hidden IS NULL"))
            # Low-stock threshold (Oct 2026). NULL = default 5 once tracked.
            if "low_stock_threshold" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN low_stock_threshold INTEGER"))
            # Estimated prep time in minutes (Oct 2026). Nullable by design —
            # NULL = unknown; the seed fills category defaults for blank rows.
            if "prep_minutes" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN prep_minutes INTEGER"))
            # Timed flash sale (F7, Oct 2026). All nullable = no flash sale;
            # old rows keep NULL and price exactly as before.
            if "sale_percent" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN sale_percent INTEGER"))
            if "sale_start" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN sale_start TIMESTAMP"))
            if "sale_end" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN sale_end TIMESTAMP"))
            # === v29: dish video (Oct 2026). NULL = no video; old dishes
            # keep NULL, so no backfill is needed. ===
            if "video_url" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN video_url TEXT"))
            # === END v29 ===
            # === v29: signature dishes (Oct 2026). All nullable: NULL
            # is_signature is treated as false; NULL signature_rank =
            # unordered. Old dishes keep NULL — no backfill is needed. ===
            if "is_signature" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN is_signature BOOLEAN DEFAULT FALSE"))
            if "signature_rank" not in cols:
                conn.execute(text("ALTER TABLE dishes ADD COLUMN signature_rank INTEGER"))
            # === END v29 ===
            # Stock can never go negative (DBA P0-2): the checkout path uses
            # an atomic conditional UPDATE, and this CHECK is the backstop.
            # Postgres only — SQLite cannot ADD CONSTRAINT without a table
            # rebuild (and DROP TABLE dishes would fail under FK
            # enforcement); fresh SQLite DBs get it from the model.
            if engine.dialect.name == "postgresql":
                exists = conn.execute(
                    text("SELECT 1 FROM pg_constraint WHERE conname = 'ck_dishes_stock_nonneg'")
                ).scalar()
                if not exists:
                    negatives = conn.execute(
                        text("SELECT COUNT(*) FROM dishes WHERE stock_quantity < 0")
                    ).scalar()
                    if not negatives:
                        conn.execute(
                            text(
                                "ALTER TABLE dishes ADD CONSTRAINT ck_dishes_stock_nonneg "
                                "CHECK (stock_quantity >= 0)"
                            )
                        )
    if "dish_options" in insp.get_table_names():
        with engine.begin() as conn:
            # One-group-per-dish UNIQUE constraint → multi-group columns (Oct
            # 2026). Old rows are preserved and backfilled to the
            # single-choice convention. Fresh DBs no-op here.
            _migrate_dish_options(conn, insp)
    if "vendors" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("vendors")}
        with engine.begin() as conn:
            # Structured shop address (Oct 2026). Legacy `area` stays untouched.
            if "street_address" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN street_address VARCHAR(120)"))
            if "apt" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN apt VARCHAR(40)"))
            if "city" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN city VARCHAR(80)"))
            if "state" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN state VARCHAR(2)"))
            if "zipcode" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN zipcode VARCHAR(10)"))
            # Zelle/Venmo payment handles (Oct 2026) — where customers send payment.
            if "zelle_handle" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN zelle_handle VARCHAR(120)"))
            if "venmo_handle" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN venmo_handle VARCHAR(120)"))
            # Shop hours (Oct 2026). All nullable = always open.
            if "prep_minutes" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN prep_minutes INTEGER DEFAULT 30"))
            conn.execute(text("UPDATE vendors SET prep_minutes = 30 WHERE prep_minutes IS NULL"))
            if "open_time" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN open_time VARCHAR(5)"))
            if "close_time" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN close_time VARCHAR(5)"))
            if "closed_weekdays" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN closed_weekdays VARCHAR(20)"))
            # Pause switch (Oct 2026) — checkout is blocked while True.
            if "is_paused" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN is_paused BOOLEAN DEFAULT FALSE"))
            conn.execute(text("UPDATE vendors SET is_paused = FALSE WHERE is_paused IS NULL"))
            # Referral share code (F2, Oct 2026). NULL for old vendors —
            # backfilled by referrals.ensure_referral_codes() at startup.
            if "referral_code" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN referral_code VARCHAR(12)"))
            # Pickup-point card (F9, Oct 2026) — all nullable; an empty card
            # is hidden, so no backfill is needed.
            if "pickup_address" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN pickup_address TEXT"))
            if "pickup_map_url" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN pickup_map_url VARCHAR(500)"))
            if "pickup_instructions" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN pickup_instructions TEXT"))
            # === v29: delivery zones + chef intro profile (Oct 2026). All
            # nullable by design: blank/NULL delivery_zips = pickup only,
            # NULL intro/chef fields = not shown. Old vendors keep NULL —
            # no backfill is needed. ===
            # NOTE: vendor.delivery_fee already exists on the model — it is
            # NOT re-added here.
            if "delivery_zips" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN delivery_zips TEXT"))
            if "intro_video_url" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN intro_video_url TEXT"))
            if "chef_name" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN chef_name VARCHAR(120)"))
            if "chef_photo_url" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN chef_photo_url TEXT"))
            if "chef_bio" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN chef_bio TEXT"))
            if "chef_bio_ar" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN chef_bio_ar TEXT"))
            # === END v29 ===
            # === v40: per-vendor commission rate (percent). NULL = use the
            # global `commission_percent` site setting. Nullable by design —
            # old vendors keep NULL, no backfill needed. ===
            if "commission_rate" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN commission_rate NUMERIC(10, 2)"))
            # === END v40 ===
            # === v46: free-delivery threshold (dollars). NULL = feature
            # off; old vendors keep NULL, no backfill needed. ===
            if "free_delivery_over" not in cols:
                conn.execute(text("ALTER TABLE vendors ADD COLUMN free_delivery_over NUMERIC(10, 2)"))
            # === END v46 ===
    if "vendor_applications" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("vendor_applications")}
        with engine.begin() as conn:
            # WA permit gate (Oct 2026). All nullable: pre-gate applications
            # keep NULL and show as "permits not on file" in the admin inbox.
            for col, ddl in (
                ("permits_food_worker_card", "BOOLEAN"),
                ("permits_food_worker_card_number", "VARCHAR(80)"),
                ("permits_food_worker_card_expiry", "DATE"),
                ("permits_establishment", "BOOLEAN"),
                ("permits_establishment_number", "VARCHAR(80)"),
                ("permits_establishment_expiry", "DATE"),
                ("permits_cottage", "BOOLEAN"),
                ("permits_cottage_number", "VARCHAR(80)"),
                ("permits_cottage_expiry", "DATE"),
                ("permits_business_license", "BOOLEAN"),
                ("permits_business_license_ubi", "VARCHAR(80)"),
                ("permits_attested", "BOOLEAN"),
            ):
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE vendor_applications ADD COLUMN {col} {ddl}"))
    if "order_items" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("order_items")}
        with engine.begin() as conn:
            # Modifier snapshot (Oct 2026), e.g. "Spice level: Extra hot (+$1.50)".
            if "modifier_label" not in cols:
                conn.execute(text("ALTER TABLE order_items ADD COLUMN modifier_label VARCHAR(200)"))
            # Multi-group modifiers (Oct 2026): modifier_label widens to TEXT
            # (several "Group: a (+$x), b (-$y)" segments joined with "; ").
            # SQLite never enforced the VARCHAR length; Postgres needs the
            # explicit widening (guarded so it runs once).
            if engine.dialect.name == "postgresql":
                cur_type = conn.execute(
                    text(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_name = 'order_items' AND column_name = 'modifier_label'"
                    )
                ).scalar()
                if cur_type not in ("text",):
                    conn.execute(text("ALTER TABLE order_items ALTER COLUMN modifier_label TYPE TEXT"))
            # Structured modifier snapshot for exact reorder re-application.
            if "modifier_detail" not in cols:
                conn.execute(text("ALTER TABLE order_items ADD COLUMN modifier_detail TEXT"))
            # Ingredient customization snapshots (Oct 2026): JSON name lists.
            if "removed_ingredients" not in cols:
                conn.execute(text("ALTER TABLE order_items ADD COLUMN removed_ingredients TEXT"))
            if "added_ingredients" not in cols:
                conn.execute(text("ALTER TABLE order_items ADD COLUMN added_ingredients TEXT"))
            # === FEATURE 5: bundle line items (Oct 2026). bundle_id is
            # nullable by design (dish lines keep NULL); old rows keep NULL.
            # dish_id becomes NULLABLE for bundle lines — databases created
            # before bundles still have NOT NULL, migrated below. ===
            if "bundle_id" not in cols:
                conn.execute(text("ALTER TABLE order_items ADD COLUMN bundle_id INTEGER"))
        # The nullability change runs after this block's ALTERs commit, on
        # its own connection (same FK-rebuild concern as customer_id) —
        # see the helper.
        _make_order_item_dish_nullable()
        # === END FEATURE 5 ===
    if "reviews" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("reviews")}
        with engine.begin() as conn:
            # Vendor reply (Oct 2026) — nullable by design, no backfill needed.
            if "vendor_reply" not in cols:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN vendor_reply TEXT"))
            if "replied_at" not in cols:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN replied_at TIMESTAMP"))
            # Customer photo reviews (Oct 2026): JSON list of up to 3 photo
            # URLs. NULL = no photos; old rows keep NULL and the code treats
            # NULL as an empty list, so no backfill UPDATE is needed.
            if "photo_urls" not in cols:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN photo_urls TEXT"))
            # === v40: review moderation. New reviews enter as 'pending';
            # every pre-v40 review is already public, so backfill 'approved'.
            # NOT NULL is enforced by the model; the backfill below covers
            # rows created between ADD COLUMN and this UPDATE. ===
            if "status" not in cols:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN status VARCHAR(20)"))
            conn.execute(text("UPDATE reviews SET status = 'approved' WHERE status IS NULL"))
            # === END v40 ===
    if "bundles" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("bundles")}
        with engine.begin() as conn:
            # === v29: holiday name, order-by cutoff, order cap (Oct 2026).
            # All nullable by design — no backfill is needed. ===
            if "holiday_name" not in cols:
                conn.execute(text("ALTER TABLE bundles ADD COLUMN holiday_name VARCHAR(80)"))
            if "order_by" not in cols:
                conn.execute(text("ALTER TABLE bundles ADD COLUMN order_by VARCHAR(10)"))
            if "max_orders" not in cols:
                conn.execute(text("ALTER TABLE bundles ADD COLUMN max_orders INTEGER"))
            # === END v29 ===
    # New tables (Oct 2026). create_all() covers fresh DBs; this backfills
    # databases created by older builds that never ran create_all for them.
    _ensure_new_tables(insp)
    # Perf indexes (Oct 2026). create_all() covers fresh DBs via index=True on the
    # models; this backfills databases created by older builds. Both SQLite and
    # PostgreSQL support CREATE INDEX IF NOT EXISTS.
    with engine.begin() as conn:
        for idx_sql in (
            "CREATE INDEX IF NOT EXISTS ix_dishes_available ON dishes (available)",
            "CREATE INDEX IF NOT EXISTS ix_dishes_is_featured ON dishes (is_featured)",
            "CREATE INDEX IF NOT EXISTS ix_order_items_dish_id ON order_items (dish_id)",
            # Barcode uniqueness per vendor (Oct 2026). NULL barcodes are
            # distinct in both SQLite and Postgres, so dishes without a
            # barcode never collide.
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_dishes_vendor_barcode ON dishes (vendor_id, barcode)",
            # Referral share codes are unique per vendor (F2, Oct 2026).
            # NULL codes (not yet backfilled) never collide.
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_vendors_referral_code ON vendors (referral_code)",
        ):
            conn.execute(text(idx_sql))
    # === v40: backfill refunded_amount from successful historical refunds.
    # Only touches rows still at 0 (idempotent); every refund path now
    # maintains the column going forward. Best-effort — never blocks startup.
    try:
        _backfill_refunded_amount()
    except Exception as exc:  # noqa: BLE001
        print(f"[ensure_schema] refunded_amount backfill skipped: {exc}")
    # === v40: create the broadcasts table on pre-v40 databases.
    # create_all() skips existing tables, so this is a no-op on fresh DBs
    # and a pure CREATE TABLE on old ones. Never blocks startup.
    try:
        from . import models as _m

        insp2 = inspect(engine)
        if "broadcasts" not in insp2.get_table_names():
            _m.Broadcast.__table__.create(engine, checkfirst=True)
            print("[ensure_schema] created broadcasts table")
    except Exception as exc:  # noqa: BLE001
        print(f"[ensure_schema] broadcasts table creation skipped: {exc}")


def _backfill_refunded_amount() -> None:
    """v40: sum successful historical refunds (from order_events) into
    orders.refunded_amount for rows still at 0.

    Idempotent: rows already carrying a value are skipped, so re-running
    (or a refund recorded between runs) can never double-count. Uses the
    same success-detection rule as the admin refund guard
    (orders._successful_refund_total). Best-effort — failures are caught
    by the caller in ensure_schema().
    """
    # Local imports: routers.orders imports this module at its top level,
    # and other helpers here use the same `from . import models as _m` pattern.
    from sqlalchemy import inspect, select, update

    from . import models as _m
    from .routers.orders import _successful_refund_total

    insp = inspect(engine)
    if "orders" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("orders")}
    if "refunded_amount" not in cols:
        return
    db = SessionLocal()
    try:
        order_ids = list(
            db.scalars(
                select(_m.Order.id).where(
                    _m.Order.refunded_amount.is_(None)
                    | (_m.Order.refunded_amount == 0)
                )
            ).all()
        )
        for oid in order_ids:
            total = _successful_refund_total(db, oid)
            if total > 0:
                db.execute(
                    update(_m.Order)
                    .where(_m.Order.id == oid)
                    .values(refunded_amount=float(total))
                )
        db.commit()
    finally:
        db.close()


def _make_customer_id_nullable() -> None:
    """Make orders.customer_id nullable on pre-guest-checkout databases.

    Fresh databases get the nullable column from create_all(); this backfills
    older ones so guest checkout works instead of 500ing with an
    IntegrityError (P1-2, 2026-10-15 audit). SQLite cannot ALTER COLUMN
    nullability, so the table is rebuilt from the model's own CREATE TABLE
    (guaranteeing the exact current schema); Postgres uses
    ALTER COLUMN ... DROP NOT NULL. Existing rows are preserved untouched.
    Idempotent: no-ops when the column is already nullable.

    Manages its own connection: the SQLite rebuild DROPs the orders table,
    which fails while FK enforcement is ON (order_items rows reference it).
    The rebuild runs with FK enforcement OFF via exec_driver_sql — which
    runs outside SQLAlchemy's autobegun transaction, so the pragma actually
    takes effect (a PRAGMA inside a transaction is a no-op). FK enforcement
    is restored in `finally` before the connection returns to the pool.
    """
    from sqlalchemy import text
    from sqlalchemy.schema import CreateTable

    from . import models as _m

    conn = engine.connect()
    try:
        if engine.dialect.name == "postgresql":
            is_nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'orders' AND column_name = 'customer_id'"
                )
            ).scalar()
            if is_nullable == "NO":
                conn.execute(text("ALTER TABLE orders ALTER COLUMN customer_id DROP NOT NULL"))
            conn.commit()
            return
        # SQLite path.
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            info = conn.execute(text("PRAGMA table_info(orders)")).mappings().all()
            col = next((r for r in info if r["name"] == "customer_id"), None)
            if col is None or not col["notnull"]:
                conn.commit()
                return  # already nullable — nothing to do
            table = _m.Order.__table__
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            ddl_new = ddl.replace("CREATE TABLE orders (", "CREATE TABLE orders_new (", 1)
            if "orders_new" not in ddl_new:
                raise RuntimeError("customer_id migration: unexpected CREATE TABLE shape")
            cols = [c.name for c in table.columns]
            collist = ", ".join(f'"{c}"' for c in cols)
            conn.execute(text(ddl_new))
            conn.execute(text(f"INSERT INTO orders_new ({collist}) SELECT {collist} FROM orders"))
            conn.execute(text("DROP TABLE orders"))
            conn.execute(text("ALTER TABLE orders_new RENAME TO orders"))
            for idx in table.indexes:
                idx.create(bind=conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    finally:
        conn.close()


def _make_order_item_dish_nullable() -> None:
    """Make order_items.dish_id nullable on pre-bundle databases.

    Fresh databases get the nullable column from create_all(); this backfills
    older ones so bundle line items (dish_id=NULL, bundle_id set) work
    instead of 500ing with an IntegrityError (same pattern as
    _make_customer_id_nullable). SQLite cannot ALTER COLUMN nullability, so
    the table is rebuilt from the model's own CREATE TABLE (guaranteeing the
    exact current schema); Postgres uses ALTER COLUMN ... DROP NOT NULL.
    Existing rows are preserved untouched. Idempotent: no-ops when the column
    is already nullable.

    Manages its own connection: the SQLite rebuild DROPs the order_items
    table, which fails while FK enforcement is ON (orders rows reference it
    only via application logic — but order_items.dish_id has a real FK to
    dishes, and the rebuild must not trip on transient states). The pragma
    dance mirrors _make_customer_id_nullable.
    """
    from sqlalchemy import text
    from sqlalchemy.schema import CreateTable

    from . import models as _m

    conn = engine.connect()
    try:
        if engine.dialect.name == "postgresql":
            is_nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'order_items' AND column_name = 'dish_id'"
                )
            ).scalar()
            if is_nullable == "NO":
                conn.execute(text("ALTER TABLE order_items ALTER COLUMN dish_id DROP NOT NULL"))
            conn.commit()
            return
        # SQLite path.
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            info = conn.execute(text("PRAGMA table_info(order_items)")).mappings().all()
            col = next((r for r in info if r["name"] == "dish_id"), None)
            if col is None or not col["notnull"]:
                conn.commit()
                return  # already nullable — nothing to do
            table = _m.OrderItem.__table__
            ddl = str(CreateTable(table).compile(dialect=engine.dialect))
            ddl_new = ddl.replace("CREATE TABLE order_items (", "CREATE TABLE order_items_new (", 1)
            if "order_items_new" not in ddl_new:
                raise RuntimeError("dish_id migration: unexpected CREATE TABLE shape")
            cols = [c.name for c in table.columns]
            collist = ", ".join(f'"{c}"' for c in cols)
            conn.execute(text(ddl_new))
            conn.execute(text(f"INSERT INTO order_items_new ({collist}) SELECT {collist} FROM order_items"))
            conn.execute(text("DROP TABLE order_items"))
            conn.execute(text("ALTER TABLE order_items_new RENAME TO order_items"))
            for idx in table.indexes:
                idx.create(bind=conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    finally:
        conn.close()


def _migrate_dish_options(conn, insp) -> None:
    """Migrate dish_options from one-group-per-dish to multi-group (Oct 2026).

    Old databases carry a UNIQUE constraint on dish_options.dish_id (a SQLite
    autoindex, or a Postgres unique constraint) plus only the
    id/dish_id/name/choices columns. The new model drops the uniqueness and
    adds selection_type/min_select/max_select.

    SQLite cannot drop a unique autoindex without a table rebuild, so the
    table is rebuilt from the model's own CREATE TABLE (guaranteeing the
    exact current schema) with every row preserved; columns the old table
    lacks are filled with the single-choice convention. Postgres gets
    ALTER TABLE ADD COLUMN plus a DROP of the old unique constraint.
    Existing rows are backfilled to selection_type='single', min_select=0,
    max_select=1. Idempotent: no-ops once the unique constraint is gone and
    the columns exist.
    """
    from sqlalchemy import text
    from sqlalchemy.schema import CreateTable

    from . import models as _m

    _BACKFILL = (
        "UPDATE dish_options SET selection_type = 'single' WHERE selection_type IS NULL",
        "UPDATE dish_options SET min_select = 0 WHERE min_select IS NULL",
        "UPDATE dish_options SET max_select = 1 "
        "WHERE max_select IS NULL AND selection_type = 'single'",
    )

    if engine.dialect.name == "postgresql":
        cols = {c["name"] for c in insp.get_columns("dish_options")}
        for col, ddl in (
            ("selection_type", "ALTER TABLE dish_options ADD COLUMN selection_type VARCHAR(10) DEFAULT 'single'"),
            ("min_select", "ALTER TABLE dish_options ADD COLUMN min_select INTEGER DEFAULT 0"),
            ("max_select", "ALTER TABLE dish_options ADD COLUMN max_select INTEGER"),
        ):
            if col not in cols:
                conn.execute(text(ddl))
        for sql in _BACKFILL:
            conn.execute(text(sql))
        # Drop the old one-group-per-dish unique constraint (the new model
        # defines no unique constraint on this table, so any contype='u'
        # here is the legacy one).
        rows = conn.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'dish_options'::regclass AND contype = 'u'"
            )
        ).all()
        for (conname,) in rows:
            conn.execute(text(f'ALTER TABLE dish_options DROP CONSTRAINT "{conname}"'))
        return

    # SQLite path: detect the legacy unique autoindex (origin 'u'; the PK
    # autoindex has origin 'pk' and the new model creates no others).
    idx_rows = conn.execute(text("PRAGMA index_list(dish_options)")).mappings().all()
    has_unique = any(r["origin"] == "u" for r in idx_rows)
    old_cols = [r["name"] for r in conn.execute(text("PRAGMA table_info(dish_options)")).mappings().all()]
    need_cols = [c for c in ("selection_type", "min_select", "max_select") if c not in old_cols]
    if not has_unique and not need_cols:
        return  # already on the new schema — nothing to do
    table = _m.DishOption.__table__
    ddl = str(CreateTable(table).compile(dialect=engine.dialect))
    ddl_new = ddl.replace("CREATE TABLE dish_options (", "CREATE TABLE dish_options_new (", 1)
    if "dish_options_new" not in ddl_new:
        raise RuntimeError("dish_options migration: unexpected CREATE TABLE shape")
    # Copy every shared column; fill missing new columns with the
    # single-choice convention (the model columns are NOT NULL without a
    # server default, so plain INSERT...SELECT would violate NOT NULL).
    defaults = {"selection_type": "'single'", "min_select": "0", "max_select": "1"}
    select_list = ", ".join(
        f'"{c}"' if c in old_cols else f"{defaults[c]}" for c in [col.name for col in table.columns]
    )
    collist = ", ".join(f'"{c}"' for c in [col.name for col in table.columns])
    conn.execute(text(ddl_new))
    conn.execute(text(f"INSERT INTO dish_options_new ({collist}) SELECT {select_list} FROM dish_options"))
    conn.execute(text("DROP TABLE dish_options"))
    conn.execute(text("ALTER TABLE dish_options_new RENAME TO dish_options"))
    for idx in table.indexes:
        idx.create(bind=conn)
    for sql in _BACKFILL:
        conn.execute(text(sql))


def _ensure_new_tables(insp) -> None:
    """Create tables for models added after the DB was first created.

    create_all() already covers fresh databases; this is the backfill for
    older databases. The import is lazy to avoid a circular import
    (models imports Base from this module).
    """
    from . import models as _m

    existing = set(insp.get_table_names())
    for model in (
        _m.PromoCode,
        _m.DishOption,
        _m.DishIngredient,
        _m.OrderMessage,
        _m.VendorApplication,
        _m.Setting,
        _m.LoyaltyLedger,
        _m.CateringRequest,
        _m.PushToken,  # Expo push tokens for the mobile app (Oct 2026)
        _m.StockMovement,  # per-dish stock history (Oct 2026)
        _m.AdminAuditLog,  # admin action audit trail (Oct 2026)
        # === FEATURE 5/8: vendor bundles + weekly pickup slots (Oct 2026) ===
        _m.Bundle,
        _m.BundleItem,
        _m.PickupSlot,
        # === END FEATURE 5/8 ===
        # === F4 (Oct 2026): zero-result search log ===
        _m.SearchQuery,
        # === F6 (Oct 2026): per-order problem reports ===
        _m.OrderProblem,
        # === New-dish announcements + community drops (Oct 2026) ===
        _m.DishAnnouncement,
        _m.DeliveryDrop,
    ):
        if model.__tablename__ not in existing:
            model.__table__.create(bind=engine)
