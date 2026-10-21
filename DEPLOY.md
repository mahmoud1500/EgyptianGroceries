# DEPLOY.md — Taking the Marketplace Live

> ⏸️ **Status: hosting is ON HOLD.** Nothing here deploys anything or costs
> money. This guide prepares everything so that when you say "go", launch
> is a checklist, not a project.

The site runs as **one app**: the Python backend serves both the API and
the two websites (customer marketplace + vendor portal). No Docker, no
build step — just Python + a Postgres database.

---

## Part 1 — Things only you can do (do these anytime)

### 1. Stripe — card payments (~10 min, free test account)
1. Sign up at https://dashboard.stripe.com and stay in **Test mode**.
2. Copy your **Secret key** (starts with `sk_test_`) → this becomes `STRIPE_SECRET_KEY`.
3. After the site is live (Part 3), add a webhook endpoint in Stripe:
   `https://YOUR-DOMAIN/api/stripe/webhook`, listening to
   `checkout.session.completed`. Copy the **Signing secret**
   (starts with `whsec_`) → this becomes `STRIPE_WEBHOOK_SECRET`.
4. Until these are set, card payments show "not configured" and cash
   orders keep working — the site never breaks.

### 2. Resend — real emails (~10 min, free tier)
1. Sign up at https://resend.com, verify your domain (they walk you through
   adding 3 DNS records).
2. Create an API key → `RESEND_API_KEY`.
3. Set `EMAIL_FROM` to something like `Osiris <orders@yourdomain.com>`
   (must use your verified domain).
4. Until this is set, order emails print to the server log instead of
   sending — the site never breaks.

### 3. Pick a domain name
Buy `something.com` from any registrar (Namecheap, Cloudflare, Google…).
You'll point it at the host in Part 3, step 4. HTTPS is free and automatic
on Render/Railway.

---

## Part 2 — Hosting options (pick one when ready)

| Option | Effort | Cost | Notes |
|---|---|---|---|
| **Render** (recommended) | ~20 min | Free tier, then ~$7/mo | Easiest: connect repo or upload, set env vars, free Postgres + free HTTPS |
| **Railway** | ~20 min | ~$5/mo | Similar to Render, nice dashboard |
| **VPS** (Hetzner/DigitalOcean) | ~1–2 hrs | ~$4–6/mo | Full control; runs `uvicorn` via systemd (see below) |

All three run the same commands — **no Docker**:

```bash
cd backend
pip install -r ../requirements.txt
# One-shot migrations FIRST (creates tables + schema updates) — then the
# workers start with SKIP_MIGRATIONS=1 so two workers never migrate
# simultaneously (two concurrent ensure_schema() runs race on ALTER TABLE
# ADD COLUMN and crash the second worker on Postgres).
python -m app.migrate
SKIP_MIGRATIONS=1 uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

> `--workers 2` is fine **only** because `SECRET_KEY` is set (Part 3).
> Without it, each worker invents its own key and logins break.

### VPS systemd service (only if you choose VPS)
Create `/etc/systemd/system/marketplace.service`:

```ini
[Unit]
Description=Egyptian Home Food Marketplace
After=network.target postgresql.service

[Service]
User=marketplace
WorkingDirectory=/opt/marketplace/backend
Environment="DATABASE_URL=postgresql+psycopg2://marketplace:STRONGPASS@localhost:5432/marketplace"
Environment="SECRET_KEY=PASTE_LONG_RANDOM_KEY"
Environment="FRONTEND_URL=https://www.yourdomain.com"
Environment="SKIP_MIGRATIONS=1"
# ... plus STRIPE_*/RESEND_* from Part 1
# Migrate once before the workers start (see Part 2): two workers running
# ensure_schema() simultaneously race and crash on Postgres.
ExecStartPre=/opt/marketplace/backend/.venv/bin/python -m app.migrate
ExecStart=/opt/marketplace/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

Then: `sudo systemctl enable --now marketplace`, and put **Caddy** in
front for automatic HTTPS:

```
www.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```

(Caddy fetches and renews the certificate itself. Point your domain's
A-record at the VPS first.)

---

## Part 3 — Launch sequence (on the production server)

Do these **in order**, once:

1. **Install + env vars.** Install Python 3.12+, create a venv, install
   `requirements.txt`. Set every variable from `backend/.env.example` —
   at minimum `SECRET_KEY` (generate:
   `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`),
   `DATABASE_URL` (your Postgres), and `FRONTEND_URL` (your domain).
2. **Create the Postgres database.** On Render/Railway: click "New Postgres"
   and paste its connection string as `DATABASE_URL` (change the scheme to
   `postgresql+psycopg2://...`). Run the one-shot migrations before
   starting the workers: `python -m app.migrate` (then start with
   `SKIP_MIGRATIONS=1` — see Part 2).
3. **Seed, then clean.** Seed the starter data, then remove the demo logins:
   ```bash
   cd backend
   DATABASE_URL="..." python -m app.seed        # vendors, dishes, demo logins
   DATABASE_URL="..." python -m app.clean_demo   # deletes demo1234 accounts + demo orders
   ```
   `clean_demo` asks you to type `YES`, shows exactly what it removes, and
   keeps all vendors/dishes. (Omar Caboose is detached from the demo vendor
   account — assign the real owner in the 👑 Admin back-office.)
4. **Create YOUR admin account.** Admins can't sign up on the website
   (by design). Run this once on the server (replace the email/password):
   ```bash
   DATABASE_URL="..." python3 - <<'EOF'
   from app.database import SessionLocal
   from app import models, auth
   db = SessionLocal()
   db.add(models.User(email="YOU@yourdomain.com",
                       hashed_password=auth.hash_password("A-STRONG-PASSWORD"),
                       name="Mahmoud", role="admin"))
   db.commit(); db.close()
   print("admin created")
   EOF
   ```
   Then log in at `https://YOUR-DOMAIN/vendor/` with it.
5. **Point the domain + HTTPS.** Render/Railway: add the custom domain in
   their dashboard and follow the DNS prompt (automatic HTTPS). VPS: Caddy
   (above).
6. **Stripe webhook** (Part 1, step 3) + **test a full order** in Stripe
   test mode, then flip Stripe to **live** keys.

---

## Part 4 — Go-live checklist

- [ ] `SECRET_KEY` is a long random string (not empty, not "changeme")
- [ ] `DATABASE_URL` points at Postgres (not SQLite)
- [ ] `FRONTEND_URL` is your real `https://` domain
- [ ] `python -m app.clean_demo` run — no `@demo.com` accounts remain
- [ ] Your real admin account created; demo passwords don't work
- [ ] Stripe **live** keys set + webhook secret set + test payment succeeds
- [ ] Resend API key set + `EMAIL_FROM` uses your verified domain + test email arrives
- [ ] Vendor(s) have real owner accounts (Omar Caboose re-assigned)
- [ ] Sample vendors/dishes you don't want are removed or hidden (vendor portal)
- [ ] Full order flow tested live: browse → cart → checkout → vendor sees it → status updates → review
- [ ] Backups: confirm your host's Postgres backup schedule (Render/Railway include daily backups)

## After launch — keep in mind

### Vendor payouts (manual settlement) — conscious process, not automation

The marketplace has **no automatic payout flow**: card money lands in your
Stripe account, and Zelle/Venmo/cash orders never pass through the platform
at all. Settlement with each vendor happens **outside the system**, by you:

1. At whatever cadence you agree (weekly is a good default), tally what each
   vendor earned: vendor portal → **Reports** (or the 👑 Admin → Vendors tab).
2. Pay the vendor out of your pocket / Stripe balance — Zelle, bank transfer,
   cash, however you both prefer.
3. **Record it immediately** in the admin back-office: `POST /api/admin/payouts`
   (Admin API — the portal's payout screen) with `{"vendor_id": N,
   "amount": 123.45, "note": "week of Oct 6, Zelle"}`.
4. The vendor can see their own payout history read-only at
   `GET /api/vendors/mine/payouts` — this is the shared ledger; if a number
   is ever disputed, this list is the source of truth.

Only the admin can create payout records (vendors can't self-report). Keep
your settlement cadence written down somewhere the vendors can see — the
tool just records; the **agreement** is the real system.

### Dish photo uploads (UPLOAD_DIR)

Vendor dish photos upload to local disk by default
(`frontend/img/uploads/`). This is wiped on every redeploy on ephemeral
hosts (Render/Railway free tiers) — the app logs a clear warning at startup
when it happens.

- Local dev / your own server with a persistent disk: the default is fine.
- Render/Railway or any ephemeral host: the real fix is **object storage**
  (Cloudflare R2 or AWS S3) — out of scope for this build; it's a backend
  change (upload the bytes to R2/S3 instead of disk) plus a small settings
  screen for the keys.
- Temporary lever if you deploy somewhere with a persistent volume: set the
  `UPLOAD_DIR` env var to that volume's path
  (e.g. `UPLOAD_DIR=/var/data/uploads`) and the app writes photos there
  instead. The startup warning goes away when `UPLOAD_DIR` is set. (Note:
  photos outside `frontend/img/uploads/` aren't served by the app's static
  mount — put the volume behind your web server or CDN's `/img/uploads/`
  path if you use this.)

- **Backups:** verify the host's Postgres backups exist before you need them.
- **Logs:** `journalctl -u marketplace -f` (VPS) or the Render/Railway log tab.
- **Updates:** upload the new `egypt.zip` over the server files, run
  `python -m app.migrate`, and restart the service. The database migrates
  via that one-shot step (never delete it).
- **Never** run the seed's demo accounts or `clean_demo` again after launch
  (it's idempotent, but there's nothing left to clean).
- Food-business permits for your area are a separate, non-software task —
  don't launch paid orders without them.
