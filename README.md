# Egyptian Home Food Marketplace 🍲

A real, runnable multi-vendor marketplace for Egyptian homemade food.
Customers browse dishes, build a cart, and check out (pickup or delivery);
vendors get their own separate website (the Vendor Portal at `/vendor/`)
with an earnings dashboard, order management, and menu editing —
both sites talk to the same API and database.

**Stack:** Python FastAPI · SQLAlchemy 2.0 · JWT auth
(python-jose + bcrypt) · Pydantic v2 · plain HTML/CSS/JS frontend served
by FastAPI itself (no Node needed, no Docker needed). Local runs use a
SQLite database file; set `DATABASE_URL` to point at PostgreSQL for hosting.

> Card payments are processed by Stripe only when `STRIPE_SECRET_KEY` is
> configured; otherwise card checkout is unavailable. Zelle, Venmo, and cash
> are recorded on the order and settled directly with the vendor. Order
> confirmation emails may be simulated when email delivery is not configured.
> Vendor notifications appear as in-portal alerts (the portal auto-refreshes).

---

## Run it on your laptop (VS Code, no Docker)

No Docker, no database server needed — just Python and a SQLite file.

### 1. Open the project
Extract the zip, then in VS Code: **File → Open Folder** → pick the
`egyptian-food-marketplace` folder (the one with `backend/` and `frontend/` inside).

### 2. One-time Python setup
In VS Code, open a terminal (`` Ctrl+` ``) and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

(`pip install` takes a few minutes the first time.)

### 3. Start the server
Every time, in the VS Code terminal, from the project folder:

```powershell
cd backend
$env:DATABASE_URL = "sqlite:///./app.db"
uvicorn app.main:app --reload
```

Or just **double-click `start-server.bat`** in the project folder — it does the same thing.

Wait for `Uvicorn running on http://127.0.0.1:8000`, then open in your browser:
- Customer site: **http://localhost:8000**
- Vendor portal: **http://localhost:8000/vendor**

Notes:
- `--reload` means: edit any file in VS Code, save, refresh the browser — no restarts needed.
- The `$env:DATABASE_URL = "sqlite:///./app.db"` line only lasts for that one terminal
  window. If you close VS Code and open a new terminal later, run it again (or use `start-server.bat`).

### 4. Seed the demo data (one time)

```powershell
cd backend
$env:DATABASE_URL = "sqlite:///./app.db"
python -m app.seed
```

This creates 4 vendors — **Omar Caboose** with his full menu, **Nile Groceries**
(33 Egyptian grocery items: pantry, spices, frozen, dairy, sweets, beverages —
23 with real photos, the rest emoji tiles),
plus 2 sample vendors — demo accounts, and 2 demo orders so the vendor
earnings dashboard has something to show. Safe to re-run — it only adds
whatever is missing, so run it again on an existing database to get
**Nile Groceries** without touching your data.

**Delivery**: vendors with delivery enabled show a Delivery option beside Pickup
at checkout. Delivery orders require a street address, which is shown with a
Google Maps link on the review page, the confirmation, the customer's order
list, and in the vendor's order detail view (with an "Open in Google Maps"
button). The database gains the `delivery_address` column automatically on
existing installs via `ensure_schema()` — no manual migration needed.

Vendor opening hours use **America/Los_Angeles** marketplace time. In the
vendor settings, closed-day numbering is Sunday-first (`0=Sunday` through
`6=Saturday`); weekly pickup-slot weekdays use Monday-first (`0=Monday` through
`6=Sunday`).

Pickup dates and times are also shown and scheduled in Pacific time, regardless
of the customer's device timezone. The server rejects past or too-soon pickup
times and checks that appointments fall on an open day, within configured
hours, and—when weekly pickup slots are enabled—at the next valid selected
slot. Stored pickup timestamps are UTC.

The admin vendor-application inbox flags claimed permits as expired, expiring
within 30 days, current, or missing an expiry date (which requires manual
verification). This is an administrative reminder, not an external permit
verification service.

### 4. Try it
Open http://localhost:8000 and:
- Browse dishes, add them with the **− / +** steppers, check out with a
  pickup time and a payment method. Zelle, Venmo, and cash are recorded for
  direct settlement; card payments use Stripe when configured.
- Log in as the vendor to see the portal: earnings, new-order alerts,
  clickable orders with a detail view (status options, activity log,
  completion-email card), menu management.

**Demo logins**

| Role     | Email              | Password  |
|----------|--------------------|-----------|
| Customer | customer@demo.com  | demo1234  |
| Vendor   | vendor@demo.com    | demo1234  |

The vendor account owns **Omar Caboose** (Mill Creek, WA — pickup only,
206-773-6068).

### 5. Stop / reset
- **Stop the server:** `Ctrl` + `C` in the terminal window running uvicorn.
- **Fresh start:** stop the server, delete `backend/app.db`, then run the seed command again.

---

## Project layout

```
start-server.bat        # double-click to start the server (sets SQLite DB, runs uvicorn --reload)
requirements.txt
backend/app/
  main.py               # FastAPI app, static frontend serving, create_all on startup
  models.py             # SQLAlchemy 2.0 models (users, vendors, dishes, orders, order_items)
  schemas.py            # Pydantic v2 validation
  auth.py               # bcrypt hashing, JWT issue/verify, role guards
  database.py           # engine + session
  seed.py               # demo data (Omar Caboose menu + Nile Groceries + sample vendors + demo accounts)
  routers/
    auth.py             # POST /api/auth/register, /login, GET /me
    vendors.py          # GET /api/vendors, /{id}, /mine, /{id}/earnings
    dishes.py           # GET /api/dishes (search/filter), POST/PATCH/DELETE (vendor)
    orders.py           # POST /api/orders, GET /api/orders, PATCH /{id}/status
frontend/
  index.html  styles.css  app.js   # plain JS single-page app
```

## API quick reference

- `POST /api/auth/register` `{name, email, password}` → `{access_token}` (customer role)
- `POST /api/auth/login` `{email, password}` → `{access_token}`
- `GET /api/vendors` · `GET /api/vendors/{id}` · `GET /api/vendors/mine` (vendor)
- `GET /api/vendors/{id}/earnings` (vendor) → `{total_revenue, order_count}`
- `GET /api/dishes?vendor_id=&category=&q=&featured=` 
- `POST /api/dishes?vendor_id=` · `PATCH /api/dishes/{id}` · `DELETE /api/dishes/{id}` (vendor, own menu)
- `POST /api/orders` `{vendor_id, items:[{dish_id, quantity}], fulfillment, pickup_at, payment_method}`
- `GET /api/orders[?vendor_id=]` · `PATCH /api/orders/{id}/status` (vendor: any forward move new→preparing→ready→completed, or cancelled)
- `GET /api/orders/{id}/events` — order activity log (placed, status changes, emails sent)
- Every order carries a timestamped activity log; marking an order **completed** records a completion email to the customer in the log (demo: simulated, shown as a preview card in the order detail view — wire to a real mailer for production).

## Notes & shortcuts taken for this test build
- `Base.metadata.create_all()` on startup instead of Alembic migrations.
- Zelle/Venmo/cash are stored as payment-method labels and settled directly with vendors. When Stripe is configured, card payments are charged through Stripe and confirmed by its webhook; without Stripe, card checkout is unavailable.
- No real email/SMTP — the customer sees a confirmation summary, the vendor sees an in-portal new-order alert,
  and the order-completed email is recorded in the order log with a preview card (simulated until wired to a real mailer).
- Multi-vendor cart: one cart can hold dishes from several vendors; checkout
  creates one sub-order per vendor and, for card payments, uses a single Stripe session for the total.

## Production checklist (before going online)

- [ ] **SECRET_KEY** — set a strong random value in the environment (`SECRET_KEY=...`).
  The app logs a loud warning and refuses to be secure while the dev fallback is in use.
  Changing it invalidates all existing login tokens (users just log in again).
- [ ] **Real emails** — set `RESEND_API_KEY` and `EMAIL_FROM` so order confirmations and
  status updates actually send (until then they are simulated/logged).
- [ ] **Stripe live keys** — add live publishable/secret keys to accept real card payments
  (test mode works without them; flipping to live also needs the food permits sorted).
- [ ] **Real domain** — point your domain at the host and set it as the canonical URL.
- [ ] **Database backups** — enable them on your Postgres provider (Neon/Supabase/Render all offer this).
