"""Egyptian Home Food Marketplace — FastAPI app.

Serves the JSON API under /api/* and the plain HTML/CSS/JS frontend
from / (static files, no Node build step needed).
"""
import asyncio
import html as html_lib
import json
import os
import re
from urllib.parse import urljoin

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import logging
from pathlib import Path
from sqlalchemy import select

log = logging.getLogger(__name__)

from . import commission_cycle, flash_sales, models
from .database import Base, SessionLocal, engine, ensure_schema
from .routers import auth as auth_router
from .routers import admin as admin_router
from .routers import announcements as announcements_router
from .routers import applications as applications_router
from .routers import catering as catering_router
from .routers import chat as chat_router
from .routers import complaints as complaints_router
from .routers import dishes as dishes_router
from .routers import delivery as delivery_router  # hybrid delivery ledger + manual dispatch
from .routers import favorites as favorites_router
from .routers import loyalty as loyalty_router
from .routers import orders as orders_router
from .routers import problems as problems_router  # F6: report-a-problem per order
from .routers import promos as promos_router
from .routers import push as push_router
from .routers import referrals as referrals_router  # F2: vendor share links
from .routers import reviews as reviews_router
from .routers import search as search_router  # F4: smart bilingual search
from .routers import settings as settings_router
from .routers import stripe as stripe_router
from .routers import vendors as vendors_router
# === FEATURE 5/8: vendor bundles + weekly pickup slots (Oct 2026) ===
from .routers import bundles as bundles_router
from .routers import pickup_slots as pickup_slots_router
from .routers import nudges as nudges_router  # v29: reorder nudges (Oct 2026)
from .routers import uploads as uploads_router  # v29: video uploads (Oct 2026)
# === END FEATURE 5/8 ===

# Resolve the frontend directory by walking up from this file until we find
# a folder that actually contains "frontend". This works both natively
# (backend/app/main.py -> project root) and on hosting (/code/app/main.py
# -> /code), no matter which cwd the app is started from.
def _find_frontend_dir() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent.parent, *here.parents]:
        if (candidate / "frontend").is_dir():
            return candidate / "frontend"
    return here.parent.parent / "frontend"  # fallback: raises a clear error


FRONTEND_DIR = _find_frontend_dir()

app = FastAPI(title="Egyptian Home Food Marketplace", version="0.1.0")

# CORS: the frontend is served by this same app, so cross-origin access is
# off by default. If the API is ever served separately from the frontend,
# set CORS_ORIGINS to a comma-separated allowlist (never "*").
_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.on_event("startup")
def _create_tables():
    # Migrations (DBA P0-1): in prod, run `python -m app.migrate` once
    # BEFORE starting workers, and start the workers with
    # SKIP_MIGRATIONS=1 — two workers running ensure_schema()
    # simultaneously race on ALTER TABLE ADD COLUMN and the second
    # crashes with "column already exists" on Postgres. Local dev keeps
    # the old behavior (migrate on startup when SKIP_MIGRATIONS is
    # unset) so the zip-upgrade flow keeps working.
    if not os.environ.get("SKIP_MIGRATIONS"):
        # Simple + robust for local testing: no migrations, just create_all
        # plus ensure_schema() for columns added after the DB was first created.
        Base.metadata.create_all(bind=engine)
        ensure_schema()
        # F2: backfill referral share codes for vendors created before the
        # share-links build. Idempotent; best-effort so a failure here can
        # never block startup.
        try:
            from . import referrals as _referrals
            from .database import SessionLocal as _SessionLocal

            _sdb = _SessionLocal()
            try:
                _referrals.ensure_referral_codes(_sdb)
            finally:
                _sdb.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("referral code backfill skipped: %s", exc)
        # Seed-data backfills (Oct 2026): in-place zip upgrades never re-run
        # `python -m app.seed`, so the idempotent seed-data fills (ingredients
        # text, category prep-minute defaults) run here on every startup.
        # Only blanks are filled — vendor edits are never overwritten.
        # Best-effort so a failure here can never block startup.
        try:
            from . import seed as _seed
            from .database import SessionLocal as _SessionLocal2

            _sdb2 = _SessionLocal2()
            try:
                _seed.fill_seed_data(_sdb2)
            finally:
                _sdb2.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("seed-data backfill skipped: %s", exc)
    else:
        log.warning(
            "SKIP_MIGRATIONS set — skipping startup migrations "
            "(run `python -m app.migrate` first)."
        )
    # Dish photo uploads default to local disk, which gets WIPED on redeploy
    # on ephemeral hosts (Render/Railway free tiers). Object storage
    # (R2/S3) is the real fix — see DEPLOY.md.
    if not os.environ.get("UPLOAD_DIR"):
        log.warning(
            "Dish photo uploads are stored on local disk and will be wiped on redeploy "
            "on ephemeral hosts (Render/Railway) — use object storage (R2/S3) for production."
        )


# Bump this on every release (egypt-v<N>) — the footers display it so the
# running build can be confirmed at a glance during debugging.
APP_VERSION = "v58"


@app.get("/api/health")
def health():
    return {"status": "ok"}


# === v48: weekly commission-cycle scheduler. Checks on startup and then
# every ~6 hours whether the configured statement weekday of the current
# week has arrived with no statements written yet, and runs the cycle.
# Failure-contained by design: a broken cycle can never crash the app.
# Disabled when DISABLE_CYCLE_SCHEDULER is set (tests / one-off scripts).
_cycle_task: asyncio.Task | None = None


def _cycle_scheduler_enabled() -> bool:
    return not os.environ.get("DISABLE_CYCLE_SCHEDULER")


async def _cycle_scheduler_loop():
    while True:
        try:
            db = SessionLocal()
            try:
                commission_cycle.maybe_run_due(db)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001 — the cycle must never take the app down
            log.warning("commission cycle scheduler check failed: %s", exc)
        await asyncio.sleep(6 * 3600)


@app.on_event("startup")
async def _start_cycle_scheduler():
    global _cycle_task
    if not _cycle_scheduler_enabled():
        log.info("DISABLE_CYCLE_SCHEDULER set — weekly commission cycle scheduler is off")
        return
    _cycle_task = asyncio.create_task(_cycle_scheduler_loop())
# === END v48 ===


@app.get("/api/version")
def version():
    return {"version": APP_VERSION}


@app.get("/api/config")
def public_config():
    """Public site config (no auth). Currently just the analytics ID —
    empty string when not configured."""
    return {"analytics_id": os.environ.get("ANALYTICS_ID", "")}


app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(announcements_router.router)  # new-dish announcements (Oct 2026)
app.include_router(applications_router.router)
app.include_router(catering_router.router)
app.include_router(chat_router.router)
app.include_router(complaints_router.router)
app.include_router(vendors_router.router)
app.include_router(dishes_router.router)
app.include_router(favorites_router.router)
app.include_router(loyalty_router.router)
app.include_router(reviews_router.router)
app.include_router(orders_router.router)
app.include_router(delivery_router.router)
app.include_router(problems_router.router)  # F6: report-a-problem per order
app.include_router(search_router.router)  # F4: smart bilingual search
app.include_router(settings_router.router)
app.include_router(promos_router.router)
app.include_router(push_router.router)
app.include_router(referrals_router.router)  # F2: /v/<code> + referral earnings
app.include_router(stripe_router.router)
# === FEATURE 5/8: vendor bundles + weekly pickup slots (Oct 2026) ===
app.include_router(bundles_router.router)
app.include_router(pickup_slots_router.router)
# === END FEATURE 5/8 ===
# === v29: reorder nudges + video uploads (Oct 2026) ===
app.include_router(nudges_router.router)
app.include_router(uploads_router.router)
# === END v29 ===


@app.middleware("http")
async def static_cache_headers(request, call_next):
    """Long browser cache for food photos; API + app shell stay uncached.

    /img/* filenames are stable (name-matched photos), so a day-long cache is
    safe and saves megabytes on repeat visits — especially on phones. The
    JS/CSS/HTML shell is deliberately left uncached so fresh zip extractions
    always take effect without a hard refresh.
    """
    resp = await call_next(request)
    if request.method == "GET" and resp.status_code == 200 and request.url.path.startswith("/img/"):
        resp.headers["Cache-Control"] = "public, max-age=86400"
        resp.headers["X-Content-Type-Options"] = "nosniff"  # P2: stop MIME sniffing on uploads
    return resp


def _seo_shell(
    request: Request,
    *,
    title: str,
    description: str,
    canonical_path: str,
    content: str,
    image_url: str | None = None,
    json_ld: dict | None = None,
) -> str:
    """Render crawlable public content into the app shell for SEO/share bots."""
    esc = lambda value: html_lib.escape(str(value or ""), quote=True)
    shell = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    base = str(request.base_url).rstrip("/")
    canonical = urljoin(base + "/", canonical_path.lstrip("/"))
    image = urljoin(base + "/", (image_url or "/img/logo.png").lstrip("/"))
    description = (description or "Homemade Egyptian food from local home cooks.")[:300]
    shell = re.sub(r"<title>.*?</title>", f"<title>{esc(title)}</title>", shell, count=1, flags=re.I | re.S)

    def set_meta(source: str, pattern: str, replacement: str) -> str:
        updated = re.sub(pattern, lambda _: replacement, source, count=1, flags=re.I)
        if updated == source:
            updated = source.replace("</head>", replacement + "\n</head>", 1)
        return updated

    shell = set_meta(shell, r'<meta name="description" content="[^"]*">',
                     f'<meta name="description" content="{esc(description)}">')
    for prop, value in (("og:title", title), ("og:description", description),
                        ("og:url", canonical), ("og:image", image),
                        ("twitter:title", title), ("twitter:description", description),
                        ("twitter:image", image)):
        attr = "name" if prop.startswith("twitter:") else "property"
        shell = set_meta(shell, rf'<meta {attr}="{re.escape(prop)}" content="[^"]*">',
                         f'<meta {attr}="{prop}" content="{esc(value)}">')
    shell = shell.replace(
        '<link rel="stylesheet" href="styles.css">',
        '<link rel="canonical" href="' + esc(canonical) + '">\n  <link rel="stylesheet" href="/styles.css">',
        1,
    )
    shell = shell.replace('src="img/logo.png"', 'src="/img/logo.png"')
    shell = shell.replace('src="i18n.js"', 'src="/i18n.js"')
    shell = shell.replace('src="app.js"', 'src="/app.js"')
    shell = shell.replace('src="chatbot.js"', 'src="/chatbot.js"')
    shell = shell.replace('<main id="app" class="container"></main>',
                          '<main id="app" class="container">' + content + '</main>', 1)
    if json_ld:
        payload = json.dumps(json_ld, ensure_ascii=False).replace("<", "\\u003c")
        shell = shell.replace("</head>", '<script type="application/ld+json">' + payload + '</script>\n</head>', 1)
    return shell


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def seo_homepage(request: Request):
    """Include real vendor and dish links in the initial HTML response."""
    db = SessionLocal()
    try:
        vendors = list(db.scalars(select(models.Vendor).order_by(models.Vendor.name).limit(30)).all())
        dishes = list(db.scalars(
            select(models.Dish)
            .where(models.Dish.available.is_(True), models.Dish.is_hidden.is_(False))
            .order_by(models.Dish.is_featured.desc(), models.Dish.name)
            .limit(24)
        ).all())
        sections = ['<section class="seo-fallback"><h1>Egyptian homemade food near you</h1>',
                    '<p>Browse homemade Egyptian dishes and groceries from local cooks. Choose pickup or delivery at checkout.</p>']
        if dishes:
            sections.append('<h2>Popular dishes</h2><ul>')
            for dish in dishes:
                vendor = next((v for v in vendors if v.id == dish.vendor_id), None)
                label = html_lib.escape(dish.name)
                if vendor:
                    label += ' · ' + html_lib.escape(vendor.name)
                sections.append(f'<li><a href="/dish/{dish.id}">{label}</a></li>')
            sections.append('</ul>')
        if vendors:
            sections.append('<h2>Local home cooks</h2><ul>')
            sections.extend(f'<li><a href="/cook/{v.id}">{html_lib.escape(v.name)}</a> · {html_lib.escape(v.area)}</li>'
                            for v in vendors)
            sections.append('</ul>')
        sections.append('</section>')
        return HTMLResponse(_seo_shell(
            request, title="Egyptian Home Food Marketplace | Homemade Egyptian Food",
            description="Order homemade Egyptian food from local cooks. Browse koshary, mahshi, molokhia, groceries, pickup and delivery.",
            canonical_path="/", content="".join(sections),
        ))
    finally:
        db.close()


@app.get("/dish/{dish_id}", response_class=HTMLResponse, include_in_schema=False)
def seo_dish_page(dish_id: int, request: Request):
    db = SessionLocal()
    try:
        dish = db.get(models.Dish, dish_id)
        if dish is None or dish.is_hidden:
            raise HTTPException(status_code=404, detail="Dish not found")
        vendor = db.get(models.Vendor, dish.vendor_id)
        title = f"{dish.name} | {vendor.name if vendor else 'Egyptian Home Food'}"
        description = dish.description or f"Order {dish.name} from {vendor.name if vendor else 'a local home cook'} for pickup or delivery."
        discount = flash_sales.effective_discount_percent(dish)
        price = float(dish.price) * (1 - discount / 100)
        image = dish.photo_url or None
        image_src = urljoin(str(request.base_url), image) if image else None
        content = '<article class="seo-fallback"><h1>' + html_lib.escape(dish.name) + '</h1>'
        if vendor:
            content += '<p>From <a href="/cook/' + str(vendor.id) + '">' + html_lib.escape(vendor.name) + '</a> · ' + html_lib.escape(vendor.area) + '</p>'
        if image:
            content += '<img src="' + html_lib.escape(image_src or image, quote=True) + '" alt="' + html_lib.escape(dish.name, quote=True) + '" style="max-width:100%;height:auto">'
        content += '<p>' + html_lib.escape(description) + '</p><p>Price: $' + format(price, '.2f') + '</p>'
        if vendor:
            content += '<p><a href="/cook/' + str(vendor.id) + '">See the menu and order</a></p>'
        content += '</article>'
        structured = {
            "@context": "https://schema.org", "@type": "MenuItem", "name": dish.name,
            "description": description,
            "offers": {"@type": "Offer", "price": format(price, '.2f'), "priceCurrency": "USD",
                       "availability": "https://schema.org/InStock" if dish.available else "https://schema.org/OutOfStock"},
        }
        if image:
            structured["image"] = urljoin(str(request.base_url), image.lstrip("/"))
        if vendor:
            structured["provider"] = {"@type": "FoodEstablishment", "name": vendor.name}
        return HTMLResponse(_seo_shell(
            request, title=title, description=description, canonical_path=f"/dish/{dish.id}",
            content=content, image_url=image, json_ld=structured,
        ))
    finally:
        db.close()


@app.get("/cook/{vendor_id}", response_class=HTMLResponse, include_in_schema=False)
def seo_vendor_page(vendor_id: int, request: Request):
    db = SessionLocal()
    try:
        vendor = db.get(models.Vendor, vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail="Vendor not found")
        dishes = list(db.scalars(
            select(models.Dish).where(models.Dish.vendor_id == vendor_id,
                                      models.Dish.available.is_(True), models.Dish.is_hidden.is_(False))
            .order_by(models.Dish.name).limit(40)
        ).all())
        title = f"{vendor.name} | Homemade Egyptian Food"
        description = vendor.tagline or f"Order homemade Egyptian food from {vendor.name} in {vendor.area}."
        content = '<article class="seo-fallback"><h1>' + html_lib.escape(vendor.name) + '</h1>'
        content += '<p>' + html_lib.escape(vendor.tagline) + ' · ' + html_lib.escape(vendor.area) + '</p>'
        content += '<h2>Menu</h2><ul>'
        for dish in dishes:
            content += '<li><a href="/dish/' + str(dish.id) + '">' + html_lib.escape(dish.name) + '</a> · $' + format(float(dish.price), '.2f') + '</li>'
        content += '</ul></article>'
        return HTMLResponse(_seo_shell(
            request, title=title, description=description, canonical_path=f"/cook/{vendor.id}",
            content=content,
        ))
    finally:
        db.close()


# Customer-facing app routes. These return the same SPA shell as `/`, allowing
# direct visits and browser refreshes to work with clean path-based URLs.
@app.get("/home", include_in_schema=False)
@app.get("/cart", include_in_schema=False)
@app.get("/checkout/review", include_in_schema=False)
@app.get("/confirmation", include_in_schema=False)
@app.get("/login", include_in_schema=False)
@app.get("/signup", include_in_schema=False)
@app.get("/orders", include_in_schema=False)
@app.get("/bundles", include_in_schema=False)
@app.get("/profile", include_in_schema=False)
@app.get("/groceries", include_in_schema=False)
@app.get("/dishes", include_in_schema=False)
@app.get("/favorites", include_in_schema=False)
@app.get("/forgot-password", include_in_schema=False)
@app.get("/forgot", include_in_schema=False)
@app.get("/reset-password", include_in_schema=False)
@app.get("/reset", include_in_schema=False)
@app.get("/verify-email", include_in_schema=False)
@app.get("/verify-email/{token}", include_in_schema=False)
@app.get("/about", include_in_schema=False)
@app.get("/faq", include_in_schema=False)
@app.get("/terms", include_in_schema=False)
@app.get("/privacy", include_in_schema=False)
@app.get("/help", include_in_schema=False)
@app.get("/apply", include_in_schema=False)
@app.get("/catering", include_in_schema=False)
@app.get("/payment-complete", include_in_schema=False)
@app.get("/checkout", include_in_schema=False)
def customer_app_page():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/orders/{order_id}/paid", include_in_schema=False)
@app.get("/orders/{order_id}", include_in_schema=False)
def customer_order_app_page(order_id: int):
    return FileResponse(FRONTEND_DIR / "index.html")

# Frontend: plain HTML/CSS/JS served by FastAPI itself.
# Two websites, one API: the customer marketplace at / and the vendor portal at /vendor/.
VENDOR_DIR = FRONTEND_DIR.parent / "frontend-vendor"
if VENDOR_DIR.is_dir():
    app.mount("/vendor", StaticFiles(directory=str(VENDOR_DIR), html=True), name="vendor-frontend")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
