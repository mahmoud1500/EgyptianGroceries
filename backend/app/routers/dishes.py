"""Dish routes: public browse/search/filter + vendor menu management."""
import csv
import datetime as dt
import io
import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, models, notifier, schemas
from ..database import get_db
from ..photo_uploads import (
    delete_uploaded_file,
    save_uploaded_photo,
    sweep_orphan_uploads,  # re-exported: admin.py imports it from here
)
from ..ratelimit import check_rate_limit
from .orders import _record_stock_movement

router = APIRouter(prefix="/api/dishes", tags=["dishes"])


@router.get("", response_model=list[schemas.DishOut])
def list_dishes(
    vendor_id: int | None = Query(default=None),
    category: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120),
    featured: bool | None = Query(default=None),
    available_only: bool = Query(default=True),
    vegetarian: bool | None = Query(default=None),
    vegan: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    caller: models.User | None = Depends(auth.get_optional_user),
):
    stmt = select(models.Dish).order_by(models.Dish.category, models.Dish.name)
    if vendor_id is not None:
        stmt = stmt.where(models.Dish.vendor_id == vendor_id)
    # Admin-moderated dishes (is_hidden) never appear in public browsing.
    # The owning vendor and the admin still see them (vendor menu, admin
    # moderation views) — everyone else gets them filtered out.
    show_hidden = False
    if caller is not None:
        if caller.role == "admin":
            show_hidden = True
        elif caller.role == "vendor" and vendor_id is not None:
            show_hidden = any(v.id == vendor_id for v in caller.vendors)
    if not show_hidden:
        stmt = stmt.where(models.Dish.is_hidden == False)  # noqa: E712
    if category:
        stmt = stmt.where(models.Dish.category == category)
    if q:
        # Escape LIKE wildcards so a search for "100%" doesn't act as a wildcard.
        safe = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{safe}%"
        stmt = stmt.where(
            models.Dish.name.ilike(like, escape="\\")
            | models.Dish.name_ar.ilike(like, escape="\\")
            | models.Dish.description.ilike(like, escape="\\")
        )
    if featured is not None:
        stmt = stmt.where(models.Dish.is_featured == featured)
    if vegetarian is not None:
        stmt = stmt.where(models.Dish.is_vegetarian == vegetarian)
    if vegan is not None:
        stmt = stmt.where(models.Dish.is_vegan == vegan)
    if available_only:
        stmt = stmt.where(models.Dish.available == True)  # noqa: E712
    dishes = list(db.scalars(stmt).all())
    _attach_ratings(db, dishes)
    _attach_options(
        db, dishes,
        include_fish_sides=caller is None or caller.role not in {"vendor", "admin"},
    )
    _attach_ingredient_options(db, dishes)
    return dishes


def _check_barcode_unique(db: Session, vendor_id: int, barcode: str | None, exclude_id: int | None = None) -> None:
    """Barcodes are unique per vendor (NULL = no barcode, never collides).
    App-level check so the vendor gets a readable 409 instead of a raw
    IntegrityError from the unique index."""
    if not barcode:
        return
    stmt = select(models.Dish).where(
        models.Dish.vendor_id == vendor_id, models.Dish.barcode == barcode
    )
    if exclude_id is not None:
        stmt = stmt.where(models.Dish.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(
            status_code=409,
            detail="Another item in your shop already uses this barcode — scan it to adjust its stock instead.",
        )


@router.get("/by-barcode", response_model=schemas.DishOut)
def get_dish_by_barcode(
    vendor_id: int,
    barcode: str = Query(min_length=1, max_length=64),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Barcode scan lookup: find the vendor's own dish with this barcode.
    Powers the scan flow — a hit opens stock-adjust instead of a duplicate."""
    _vendor_for(user, vendor_id, db)
    dish = db.scalar(
        select(models.Dish).where(
            models.Dish.vendor_id == vendor_id, models.Dish.barcode == barcode.strip()
        )
    )
    if dish is None:
        raise HTTPException(status_code=404, detail="No item with this barcode in your shop.")
    _attach_ratings(db, [dish])
    _attach_options(db, [dish])
    _attach_ingredient_options(db, [dish])
    return dish


@router.post("/{dish_id}/stock-adjust", response_model=schemas.DishOut)
def adjust_stock(
    dish_id: int,
    payload: schemas.StockAdjustIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Relative stock change from the barcode scan flow (+received / −sold).
    Result clamped at 0. NULL (unlimited) stock: a positive delta starts
    tracking at that value; a negative delta leaves it unlimited.
    Recorded as an 'adjust' stock movement."""
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    _vendor_for(user, dish.vendor_id, db)
    before = dish.stock_quantity
    if dish.stock_quantity is None:
        dish.stock_quantity = payload.delta if payload.delta > 0 else None
    else:
        dish.stock_quantity = max(dish.stock_quantity + payload.delta, 0)
    if dish.stock_quantity != before:
        _record_stock_movement(
            db, dish, (dish.stock_quantity or 0) - (before or 0), "adjust"
        )
    db.commit()
    db.refresh(dish)
    _attach_ratings(db, [dish])
    _attach_options(db, [dish])
    _attach_ingredient_options(db, [dish])
    return dish


@router.get("/{dish_id}/stock-movements", response_model=list[schemas.StockMovementOut])
def stock_movements(
    dish_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Stock history for one dish — vendor owner or admin only."""
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    if user.role == "admin":
        pass
    elif user.role == "vendor":
        _vendor_for(user, dish.vendor_id, db)
    else:
        raise HTTPException(status_code=403, detail="Not your dish")
    return list(
        db.scalars(
            select(models.StockMovement)
            .where(models.StockMovement.dish_id == dish_id)
            .order_by(models.StockMovement.created_at.desc(), models.StockMovement.id.desc())
            .limit(limit)
        ).all()
    )


@router.post("/{dish_id}/restock", response_model=schemas.DishOut)
def restock_dish(
    dish_id: int,
    payload: schemas.RestockIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Restock flow: add `quantity` units to a dish, recorded as a
    'restock' movement. Starts tracking (NULL → quantity) for untracked dishes."""
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    _vendor_for(user, dish.vendor_id, db)
    dish.stock_quantity = (dish.stock_quantity or 0) + payload.quantity
    _record_stock_movement(db, dish, payload.quantity, "restock")
    db.commit()
    db.refresh(dish)
    _attach_ratings(db, [dish])
    _attach_options(db, [dish])
    _attach_ingredient_options(db, [dish])
    return dish


@router.post("/bulk-stock", response_model=list[schemas.DishOut])
def bulk_stock(
    payload: schemas.BulkStockIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Bulk stock management: set absolute quantities for many dishes in
    one call. Quantities validated ≥ 0. Each changed dish gets an 'adjust'
    movement. All dishes must belong to the caller's shop."""
    _vendor_for(user, payload.vendor_id, db)
    updated: list[models.Dish] = []
    for item in payload.items:
        dish = db.get(models.Dish, item.dish_id)
        if dish is None:
            raise HTTPException(status_code=404, detail=f"Dish {item.dish_id} not found")
        if dish.vendor_id != payload.vendor_id:
            raise HTTPException(status_code=403, detail="Not your dish")
        before = dish.stock_quantity
        if before != item.stock_quantity:
            dish.stock_quantity = item.stock_quantity
            _record_stock_movement(
                db, dish, (item.stock_quantity or 0) - (before or 0), "adjust"
            )
        updated.append(dish)
    db.commit()
    for dish in updated:
        db.refresh(dish)
    _attach_ratings(db, updated)
    _attach_options(db, updated)
    _attach_ingredient_options(db, updated)
    return updated


def _attach_ingredient_options(db: Session, dishes: list[models.Dish]) -> None:
    """Fill `ingredient_options` on dish objects with ONE query (avoids N+1)."""
    if not dishes:
        return
    by_dish: dict[int, list[models.DishIngredient]] = {}
    for ing in db.scalars(
        select(models.DishIngredient).where(
            models.DishIngredient.dish_id.in_([d.id for d in dishes])
        )
    ).all():
        by_dish.setdefault(ing.dish_id, []).append(ing)
    for d in dishes:
        d.ingredient_options = by_dish.get(d.id, [])




_FISH_SIDE_CHOICES = [{"label":"Rice","delta":0},{"label":"French fries","delta":0},{"label":"Tahini salad","delta":0},{"label":"Egyptian salad","delta":0}]

def _default_fish_sides(dish: models.Dish) -> bool:
    """Whether this exact catalog item gets the built-in included-side group."""
    return (
        dish.name.strip().casefold() == "whole grilled fish"
        and float(dish.price) == 18.0
    )

def _fish_sides_group(dish: models.Dish, option_id: int) -> models.DishOption:
    """Transient group: expose default sides without writing to production DB."""
    return models.DishOption(
        id=option_id,
        dish_id=dish.id,
        name="Sides",
        selection_type="multiple",
        min_select=0,
        max_select=None,
        choices=json.dumps(_FISH_SIDE_CHOICES),
    )

def _attach_options(
    db: Session,
    dishes: list[models.Dish],
    *,
    include_fish_sides: bool = False,
) -> None:
    """Fill option groups in one query; optional public defaults are transient."""
    if not dishes:
        return
    by_dish: dict[int, list[models.DishOption]] = {}
    for opt in db.scalars(
        select(models.DishOption).where(
            models.DishOption.dish_id.in_([d.id for d in dishes])
        )
    ).all():
        by_dish.setdefault(opt.dish_id, []).append(opt)
    for d in dishes:
        groups = by_dish.get(d.id, [])
        if include_fish_sides and _default_fish_sides(d):
            side_idx = next((i for i, g in enumerate(groups) if (g.name or "").strip().casefold() == "sides"), None)
            if side_idx is None:
                groups = groups + [_fish_sides_group(d, -d.id)]
            else:
                # Present the requested menu choices without mutating the ORM row.
                groups = list(groups)
                groups[side_idx] = _fish_sides_group(d, groups[side_idx].id)
        d.options = groups


def _attach_ratings(db: Session, dishes: list[models.Dish]) -> None:
    """Fill avg_rating/rating_count on dish objects with ONE aggregate query.

    v40: counts APPROVED reviews only (pending/hidden never affect stars)."""
    if not dishes:
        return
    agg = {
        did: (cnt, float(avg or 0))
        for did, cnt, avg in db.execute(
            select(
                models.Review.dish_id,
                func.count(models.Review.id),
                func.avg(models.Review.rating),
            )
            .where(
                models.Review.dish_id.in_([d.id for d in dishes]),
                models.Review.dish_id.isnot(None),
                models.Review.status == "approved",
            )
            .group_by(models.Review.dish_id)
        ).all()
    }
    for d in dishes:
        cnt, avg = agg.get(d.id, (0, 0.0))
        d.avg_rating = round(avg, 1)
        d.rating_count = int(cnt)


@router.get("/bestsellers", response_model=list[schemas.DishOut])
def bestsellers(limit: int = Query(default=10, ge=1, le=30), db: Session = Depends(get_db)):
    """Top dishes by total ordered quantity (non-cancelled orders only)."""
    rows = db.execute(
        select(models.Dish, func.coalesce(func.sum(models.OrderItem.quantity), 0).label("sold"))
        .join(models.OrderItem, models.OrderItem.dish_id == models.Dish.id)
        .join(models.Order, models.Order.id == models.OrderItem.order_id)
        .where(models.Order.status != "cancelled", models.Dish.available == True, models.Dish.is_hidden == False)  # noqa: E712
        .group_by(models.Dish.id)
        .order_by(func.coalesce(func.sum(models.OrderItem.quantity), 0).desc())
        .limit(limit)
    ).all()
    dishes = [r[0] for r in rows]
    _attach_ratings(db, dishes)
    _attach_options(db, dishes)
    _attach_ingredient_options(db, dishes)
    return dishes


# === FEATURE 7: timed flash sales ===
# NOTE: this route MUST stay registered before GET /{dish_id} below —
# FastAPI matches in registration order and "flash-sales" would otherwise
# be swallowed by the /{dish_id} path (422 on int conversion).
@router.get("/flash-sales", response_model=list[schemas.DishOut])
def flash_sales(
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Dishes with a LIVE flash sale right now (server-filtered by time).

    Only available, non-hidden dishes whose sale window covers "now" in
    America/Los_Angeles. The window is evaluated server-side so a stale or
    tampered client can never see (or be charged) a sale that isn't live.
    """
    import datetime as _dt

    from .. import flash_sales as _fs

    now = _dt.datetime.now(_fs.LA)
    stmt = (
        select(models.Dish)
        .where(
            models.Dish.available == True,  # noqa: E712
            models.Dish.is_hidden == False,  # noqa: E712
            models.Dish.sale_percent.is_not(None),
            models.Dish.sale_percent > 0,
        )
        .order_by(models.Dish.sale_percent.desc())
    )
    live = [d for d in db.scalars(stmt).all() if _fs.flash_sale_active(d, now)][:limit]
    _attach_ratings(db, live)
    _attach_options(db, live)
    _attach_ingredient_options(db, live)
    return live
# === END FEATURE 7 ===


@router.post("/photo-upload")
def upload_dish_photo(
    request: Request,
    file: UploadFile = File(...),
    user: models.User = Depends(auth.require_vendor),
):
    """Upload a dish photo file; returns the URL to store as photo_url."""
    # P1-3 (2026-10-15 audit): cap uploads at 20/hour per IP so a vendor
    # can't fill the disk with unbounded 5 MB files.
    check_rate_limit(request, "dish_photo_upload", limit=20, window_seconds=3600)
    return {"photo_url": save_uploaded_photo(file)}


@router.get("/{dish_id}", response_model=schemas.DishOut)
def get_dish(
    dish_id: int,
    db: Session = Depends(get_db),
    caller: models.User | None = Depends(auth.get_optional_user),
):
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    # Admin-hidden dishes look "not found" to everyone except the owning
    # vendor and the admin (don't leak the moderation state).
    if dish.is_hidden:
        allowed = False
        if caller is not None:
            if caller.role == "admin":
                allowed = True
            elif caller.role == "vendor":
                allowed = any(v.id == dish.vendor_id for v in caller.vendors)
        if not allowed:
            raise HTTPException(status_code=404, detail="Dish not found")
    _attach_ratings(db, [dish])
    _attach_options(
        db, [dish],
        include_fish_sides=caller is None or caller.role not in {"vendor", "admin"},
    )
    _attach_ingredient_options(db, [dish])
    return dish


def _vendor_for(user: models.User, vendor_id: int, db: Session) -> models.Vendor:
    vendor = db.get(models.Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return auth.vendor_owned_by(vendor, user)


@router.post("", response_model=schemas.DishCreateOut, status_code=201)
def create_dish(
    request: Request,
    vendor_id: int,
    payload: schemas.DishCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    # Security P2 (2026-10-18): each create push-spams the vendor's past
    # customers, so cap dish creation at 20/hour per IP — same shape as
    # dish_photo_upload above.
    check_rate_limit(request, "dish_create", limit=20, window_seconds=3600)
    _vendor_for(user, vendor_id, db)
    data = payload.model_dump()
    _check_barcode_unique(db, vendor_id, data.get("barcode"))
    # available_days is a JSON TEXT column; the schema hands us a list/None.
    data["available_days"] = json.dumps(data["available_days"]) if data["available_days"] is not None else None
    dish = models.Dish(vendor_id=vendor_id, **data)
    db.add(dish)
    db.commit()
    db.refresh(dish)
    dish.options = []
    dish.ingredient_options = []
    # === New-dish announcements (Oct 2026): AFTER the commit — announce to
    # the vendor's past customers (Expo push) and record one
    # DishAnnouncement row. Never raises: a notification failure must not
    # break dish creation. NOT hooked into the bulk-import endpoint. ===
    announced_to = _announce_new_dish(db, dish)
    out = schemas.DishCreateOut.model_validate(dish)
    out.announced_to = announced_to
    return out


def _announce_new_dish(db: Session, dish: models.Dish) -> int:
    """Announce a newly created dish to the vendor's past customers.

    Creates the (one-per-dish) DishAnnouncement row and pushes it via Expo
    to the past customers' registered devices. Returns the number of past
    customers announced to (0 when none / on any failure). Never raises.
    """
    try:
        # One announcement per dish — no re-announce on edit. (Edits go
        # through PATCH, which never calls this.)
        existing = (
            db.query(models.DishAnnouncement)
            .filter(models.DishAnnouncement.dish_id == dish.id)
            .one_or_none()
        )
        if existing is not None:
            return 0
        # Distinct past customer ids for this vendor. Guest orders carry
        # customer_id NULL and are excluded — pushes are tied to accounts.
        customer_ids = list(
            db.scalars(
                select(models.Order.customer_id)
                .where(
                    models.Order.vendor_id == dish.vendor_id,
                    models.Order.customer_id.is_not(None),
                )
                .distinct()
            ).all()
        )
        # Explicit microsecond-precision created_at: SQLite truncates the
        # column's server-side func.now() to whole seconds, while
        # mark_announcements_seen stores microsecond timestamps — a dish
        # announced in the same whole second as the seen-mark would be
        # wrongly flagged seen (created_at > seen_at fails at second
        # precision). The column's server_default remains as a fallback for
        # other creation paths.
        db.add(
            models.DishAnnouncement(
                vendor_id=dish.vendor_id,
                dish_id=dish.id,
                created_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()
        if customer_ids:
            vendor_name = dish.vendor.name if dish.vendor else ""
            title = f"New dish from {vendor_name}"
            body = (
                f"{dish.name} just joined the menu at {vendor_name}! 🎉\n"
                f"{dish.name} انضم للمنيو عند {vendor_name}! 🎉"
            )
            tokens = (
                db.query(models.PushToken)
                .filter(models.PushToken.user_id.in_(customer_ids))
                .all()
            )
            try:
                notifier.send_push_to_tokens(
                    db, tokens, title, body, data={"dishId": dish.id}
                )
            except Exception as exc:  # noqa: BLE001 — push is best-effort
                print(f"[dishes] announcement push failed ({exc})")
        return len(customer_ids)
    except Exception as exc:  # noqa: BLE001 — announcements never break dish creation
        print(f"[dishes] _announce_new_dish failed ({exc})")
        try:
            db.rollback()
        except Exception:
            pass
        return 0


# ---- bulk CSV dish import (vendor portal, Oct 2026) ----
BULK_IMPORT_MAX_BYTES = 1_000_000  # ~1MB
BULK_IMPORT_MAX_ROWS = 500

# Canonical column -> accepted header spellings (the portal downloads the
# template in the vendor's language, so both English and Arabic headers
# must parse). Matching is case-insensitive after stripping whitespace.
BULK_COLUMNS = {
    "name": ("name", "الاسم"),
    "name_ar": ("name_ar", "الاسم بالعربية"),
    "price": ("price", "السعر"),
    "category": ("category", "الفئة"),
    "description": ("description", "الوصف"),
    "available": ("available", "متاح"),
    "stock_quantity": ("stock_quantity", "الكمية بالمخزون"),
}
_BULK_HEADER_MAP = {
    alias.strip().casefold(): canon
    for canon, aliases in BULK_COLUMNS.items()
    for alias in aliases
}
_BULK_TRUE = {"yes", "y", "true", "1", "نعم"}
_BULK_FALSE = {"no", "n", "false", "0", "لا"}


def _parse_bulk_row(raw: dict, row_num: int) -> tuple[dict | None, bool | None, schemas.BulkImportError | None]:
    """Parse one CSV row -> (dish_kwargs, available, None) or (None, None, error).

    Every cell is treated as plain text — formula-looking values (=, +, -, @
    prefixes) are never evaluated, just stored literally. There is no name_ar
    column on the model, so an Arabic name is carried at the start of the
    description (the codebase's existing convention).
    """
    def err(code: str, message: str) -> tuple[None, None, schemas.BulkImportError]:
        return None, None, schemas.BulkImportError(row=row_num, code=code, message=message)

    name = (raw.get("name") or "").strip()
    if not name:
        return err("name_required", "Name is required.")
    price_raw = (raw.get("price") or "").strip()
    try:
        price = float(price_raw)
    except (TypeError, ValueError):
        return err("price_invalid", f"Price '{price_raw}' is not a number.")
    if price < 0:
        return err("price_negative", f"Price {price_raw} cannot be negative.")
    avail_raw = (raw.get("available") or "").strip().casefold()
    if not avail_raw:
        available = True
    elif avail_raw in _BULK_TRUE:
        available = True
    elif avail_raw in _BULK_FALSE:
        available = False
    else:
        return err("available_invalid", f"Available '{raw.get('available')}' must be yes/no.")
    stock_raw = (raw.get("stock_quantity") or "").strip()
    if not stock_raw:
        stock = None
    else:
        try:
            stock = int(stock_raw)
        except (TypeError, ValueError):
            return err("stock_invalid", f"Stock '{stock_raw}' is not a whole number.")
        if stock < 0:
            return err("stock_invalid", f"Stock {stock_raw} cannot be negative.")
    name_ar = (raw.get("name_ar") or "").strip()
    description = (raw.get("description") or "").strip()
    if name_ar:
        description = f"{name_ar}\n{description}".strip()
    kwargs = {
        "name": name,
        "description": description,
        "price": price,
        "category": (raw.get("category") or "").strip() or "Mains",
        "stock_quantity": stock,
    }
    # Same validation rules as single-dish creation — DishCreate is the
    # authority, so the bulk path can never be more lenient than the form.
    try:
        dish_in = schemas.DishCreate(**kwargs)
    except ValidationError as e:
        first = e.errors()[0]
        return err("dish_invalid", f"{'.'.join(str(l) for l in first['loc'])}: {first['msg']}")
    return dish_in, available, None


@router.post("/bulk-import", response_model=schemas.BulkImportOut)
def bulk_import_dishes(
    vendor_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Import dishes from a CSV file into the vendor's OWN store.

    Partial success by design: valid rows are created, bad rows are reported
    per row (1-based spreadsheet numbers) so the vendor can fix and re-upload
    just those. _vendor_for guarantees a vendor can never import into
    another vendor's store.
    """
    _vendor_for(user, vendor_id, db)
    check_rate_limit(request, "dish_bulk_import", limit=10, window_seconds=3600)
    raw = file.file.read(BULK_IMPORT_MAX_BYTES + 1)
    if len(raw) > BULK_IMPORT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 1 MB.")
    try:
        text = raw.decode("utf-8-sig")  # utf-8-sig strips a BOM if present
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded CSV.")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV is empty.")
    headers: dict[str, str] = {}  # actual header text -> canonical column
    for h in reader.fieldnames:
        canon = _BULK_HEADER_MAP.get((h or "").strip().casefold())
        if canon is None:
            raise HTTPException(status_code=400, detail=f"Unknown column '{h}'.")
        if canon in headers.values():
            raise HTTPException(status_code=400, detail=f"Duplicate column '{h}'.")
        headers[h] = canon
    rows = list(reader)
    if len(rows) > BULK_IMPORT_MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many rows ({len(rows)}). Maximum is {BULK_IMPORT_MAX_ROWS} per import.",
        )
    created = 0
    errors: list[schemas.BulkImportError] = []
    for i, raw_row in enumerate(rows, start=2):  # row 1 = header
        row = {headers[h]: (raw_row.get(h) or "") for h in reader.fieldnames}
        # Skip fully-blank rows silently (trailing newlines in spreadsheets).
        if not any((v or "").strip() for v in row.values()):
            continue
        dish_in, available, error = _parse_bulk_row(row, i)
        if error is not None:
            errors.append(error)
            continue
        data = dish_in.model_dump()
        data["available_days"] = (
            json.dumps(data["available_days"]) if data["available_days"] is not None else None
        )
        db.add(models.Dish(vendor_id=vendor_id, available=available, **data))
        created += 1
    db.commit()
    return schemas.BulkImportOut(created=created, failed=len(errors), errors=errors)


@router.patch("/{dish_id}", response_model=schemas.DishOut)
def update_dish(
    dish_id: int,
    payload: schemas.DishUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    _vendor_for(user, dish.vendor_id, db)
    updates = payload.model_dump(exclude_unset=True)
    # is_hidden is admin-only moderation: a vendor PATCH can never set or
    # clear it (a vendor could otherwise un-hide a moderated dish).
    updates.pop("is_hidden", None)
    if "barcode" in updates:
        _check_barcode_unique(db, dish.vendor_id, updates["barcode"], exclude_id=dish.id)
    # === FEATURE 7: flash sale — merge partial updates with the dish's
    # current values before validating (a PATCH may set only sale_percent).
    if any(k in updates for k in ("sale_percent", "sale_start", "sale_end")):
        merged_pct = updates.get("sale_percent", dish.sale_percent)
        merged_start = updates.get("sale_start", dish.sale_start)
        merged_end = updates.get("sale_end", dish.sale_end)
        try:
            schemas._validate_flash_sale(merged_pct, merged_start, merged_end)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        updates["sale_percent"] = merged_pct
        updates["sale_start"] = merged_start
        updates["sale_end"] = merged_end
    # === END FEATURE 7 ===
    if "available_days" in updates:
        updates["available_days"] = (
            json.dumps(updates["available_days"]) if updates["available_days"] is not None else None
        )
    if "photo_url" in updates and updates["photo_url"] != dish.photo_url:
        delete_uploaded_file(dish.photo_url)  # replaced upload: don't orphan the file
    # === v29: dish video + signature dishes (Oct 2026) ===
    if "video_url" in updates and updates["video_url"] != dish.video_url:
        delete_uploaded_file(dish.video_url)  # replaced video: don't orphan the file
    if updates.get("is_signature") is True and not dish.is_signature:
        # Turning a 6th dish into a signature is a 422; unsetting is always
        # allowed. is_signature is a nullable BOOLEAN — NULL counts as false.
        sig_count = db.scalar(
            select(func.count())
            .select_from(models.Dish)
            .where(
                models.Dish.vendor_id == dish.vendor_id,
                models.Dish.is_signature.is_(True),
            )
        )
        if (sig_count or 0) >= 5:
            raise HTTPException(
                status_code=422,
                detail="A vendor can have at most 5 signature dishes — unset one first",
            )
    # === END v29 ===
    for field, value in updates.items():
        setattr(dish, field, value)
    db.commit()
    db.refresh(dish)
    _attach_options(db, [dish])
    _attach_ingredient_options(db, [dish])
    return dish


@router.delete("/{dish_id}", status_code=204)
def delete_dish(
    dish_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    _vendor_for(user, dish.vendor_id, db)
    # Never orphan order history: a dish on any order can't be deleted.
    used = db.scalar(
        select(func.count())
        .select_from(models.OrderItem)
        .where(models.OrderItem.dish_id == dish_id)
    )
    if used:
        raise HTTPException(
            status_code=400,
            detail="This dish is on past orders and can't be deleted — mark it unavailable instead.",
        )
    # History that references the dish: favorites, reviews, and stock
    # movements all FK-reference dishes with no cascade. On Postgres the
    # DELETE would 500 with an IntegrityError (SQLite's FK enforcement
    # being off hid this in dev — DBA P0-3). Same hide-instead rule.
    blockers = []
    for model, label in (
        (models.Favorite, "favorited"),
        (models.Review, "reviewed"),
        (models.StockMovement, "has stock history"),
    ):
        if db.scalar(
            select(func.count()).select_from(model).where(model.dish_id == dish_id)
        ):
            blockers.append(label)
    if blockers:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This dish can't be deleted because it {', '.join(blockers)} "
                "— mark it unavailable instead."
            ),
        )
    db.delete(dish)
    db.commit()
    delete_uploaded_file(dish.photo_url)
    return None


# ---------- dish modifiers (multiple option groups per dish) ----------
def _get_dish_owned(dish_id: int, user: models.User, db: Session) -> models.Dish:
    dish = db.get(models.Dish, dish_id)
    if dish is None:
        raise HTTPException(status_code=404, detail="Dish not found")
    _vendor_for(user, dish.vendor_id, db)
    return dish


def _validate_merged_option_config(
    current: models.DishOption, updates: dict
) -> tuple[str, int, int | None, list[dict] | None]:
    """Validate the merged (current + updates) group configuration.

    Returns the effective (selection_type, min_select, max_select, choices).
    choices comes back as a list of {"label", "delta"} dicts (or None when
    unchanged).
    """
    selection_type = updates.get("selection_type", current.selection_type or "single")
    min_select = updates.get("min_select", current.min_select if current.min_select is not None else 0)
    max_select = updates.get("max_select", current.max_select)
    if "choices" in updates:
        raw_choices = updates["choices"]
        choices = [c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in raw_choices]
    else:
        choices = None
    schemas._validate_option_config(selection_type, min_select, max_select, None)
    if choices is not None:
        # Reuse the choice-level validation (labels unique, deltas in range).
        parsed = [schemas.DishOptionChoice(**c) for c in choices]
        schemas._validate_option_config(selection_type, min_select, max_select, parsed)
        choices = [c.model_dump() for c in parsed]
    if selection_type == "single":
        max_select = 1
    return selection_type, min_select, max_select, choices


def _validate_choice_dish_links(dish, choices, db):
    """A choice's linked dish_id (if any) must be one of the vendor's own
    dishes, and not the dish the group belongs to."""
    for c in choices or []:
        did = c.get("dish_id") if isinstance(c, dict) else getattr(c, "dish_id", None)
        if not did:
            continue
        linked = db.get(models.Dish, did)
        if linked is None or linked.vendor_id != dish.vendor_id or linked.id == dish.id:
            raise HTTPException(status_code=400, detail=f"Linked dish #{did} is not one of your other dishes")


@router.post("/{dish_id}/options", response_model=schemas.DishOptionOut, status_code=201)
def create_dish_option(
    dish_id: int,
    payload: schemas.DishOptionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Create a modifier group for a dish. A dish may have SEVERAL groups
    (single- and/or multiple-choice)."""
    dish = _get_dish_owned(dish_id, user, db)
    _validate_choice_dish_links(dish, [c.model_dump() for c in payload.choices], db)
    opt = models.DishOption(
        dish_id=dish.id,
        name=payload.name,
        selection_type=payload.selection_type,
        min_select=payload.min_select,
        max_select=payload.max_select,  # normalized to 1 for single by the schema
        choices=json.dumps([c.model_dump() for c in payload.choices]),
    )
    db.add(opt)
    db.commit()
    db.refresh(opt)
    return opt


@router.patch("/{dish_id}/options/{option_id}", response_model=schemas.DishOptionOut)
def update_dish_option(
    dish_id: int,
    option_id: int,
    payload: schemas.DishOptionUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Edit a modifier group (name, type, min/max, choices). Only the fields
    sent are changed; the merged configuration is validated."""
    dish = _get_dish_owned(dish_id, user, db)
    opt = db.get(models.DishOption, option_id)
    if opt is None or opt.dish_id != dish.id:
        raise HTTPException(status_code=404, detail="Option not found")
    updates = payload.model_dump(exclude_unset=True)
    try:
        selection_type, min_select, max_select, choices = _validate_merged_option_config(opt, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    opt.selection_type = selection_type
    opt.min_select = min_select
    opt.max_select = max_select
    if "name" in updates:
        opt.name = updates["name"]
    if choices is not None:
        _validate_choice_dish_links(dish, choices, db)
        opt.choices = json.dumps(choices)
    db.commit()
    db.refresh(opt)
    return opt


@router.get("/{dish_id}/options", response_model=list[schemas.DishOptionOut])
def list_dish_options(
    dish_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    dish = _get_dish_owned(dish_id, user, db)
    return list(
        db.scalars(
            select(models.DishOption).where(models.DishOption.dish_id == dish.id)
        ).all()
    )


@router.delete("/{dish_id}/options/{option_id}", status_code=204)
def delete_dish_option(
    dish_id: int,
    option_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    dish = _get_dish_owned(dish_id, user, db)
    opt = db.get(models.DishOption, option_id)
    if opt is None or opt.dish_id != dish.id:
        raise HTTPException(status_code=404, detail="Option not found")
    db.delete(opt)
    db.commit()
    return None


# ---------- dish ingredients (customizable) ----------
@router.get("/{dish_id}/ingredients", response_model=list[schemas.DishIngredientOut])
def list_dish_ingredients(
    dish_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    dish = _get_dish_owned(dish_id, user, db)
    return list(
        db.scalars(
            select(models.DishIngredient)
            .where(models.DishIngredient.dish_id == dish.id)
            .order_by(models.DishIngredient.id)
        ).all()
    )


@router.post("/{dish_id}/ingredients", response_model=schemas.DishIngredientOut, status_code=201)
def create_dish_ingredient(
    dish_id: int,
    payload: schemas.DishIngredientCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Add a customizable ingredient to a dish (removable default ingredient
    or paid add-on)."""
    dish = _get_dish_owned(dish_id, user, db)
    ing = models.DishIngredient(dish_id=dish.id, **payload.model_dump())
    db.add(ing)
    db.commit()
    db.refresh(ing)
    return ing


@router.patch("/{dish_id}/ingredients/{ing_id}", response_model=schemas.DishIngredientOut)
def update_dish_ingredient(
    dish_id: int,
    ing_id: int,
    payload: schemas.DishIngredientUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    """Edit a dish ingredient. Only the fields sent are changed; the merged
    configuration is validated (e.g. allergen_name required when is_allergen)."""
    dish = _get_dish_owned(dish_id, user, db)
    ing = db.get(models.DishIngredient, ing_id)
    if ing is None or ing.dish_id != dish.id:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    updates = payload.model_dump(exclude_unset=True)
    merged = {
        "name": updates.get("name", ing.name),
        "extra_price": updates.get("extra_price", float(ing.extra_price or 0)),
        "is_allergen": updates.get("is_allergen", ing.is_allergen),
        "allergen_name": updates.get("allergen_name", ing.allergen_name),
    }
    try:
        merged["allergen_name"] = schemas._ingredient_config_ok(
            merged["name"], merged["extra_price"], merged["is_allergen"], merged["allergen_name"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if "name" in updates:
        updates["name"] = updates["name"].strip()
        if not updates["name"]:
            raise HTTPException(status_code=400, detail="ingredient name must not be blank")
    if "extra_price" in updates:
        updates["extra_price"] = round(updates["extra_price"], 2)
    if "allergen_name" in updates or "is_allergen" in updates:
        updates["allergen_name"] = merged["allergen_name"]
        if not merged["is_allergen"]:
            updates["allergen_name"] = None  # don't keep a stale allergen name
    for field, value in updates.items():
        setattr(ing, field, value)
    db.commit()
    db.refresh(ing)
    return ing


@router.delete("/{dish_id}/ingredients/{ing_id}", status_code=204)
def delete_dish_ingredient(
    dish_id: int,
    ing_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_vendor),
):
    dish = _get_dish_owned(dish_id, user, db)
    ing = db.get(models.DishIngredient, ing_id)
    if ing is None or ing.dish_id != dish.id:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    db.delete(ing)
    db.commit()
    return None
