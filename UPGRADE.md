# Upgrading to a new version — the easy way

You do **not** need a new folder, a new venv, or a re-seed for each version.
Keep ONE folder (e.g. `C:\projects\egypt`) and upgrade it in place.

## Upgrade steps (every new version)

1. Download the new `egypt-vN.zip`.
2. Extract it **into your existing project folder**, choosing **"Replace all" /
   "Overwrite"** when asked.
   - Your `backend/app.db` (your data) is NOT in the zip → it survives.
   - Your `.venv` folder is NOT in the zip → it survives.
3. In the VS Code terminal (project root folder):
   ```
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   This installs only what's new or missing (fast when nothing changed).
4. Restart the server:
   ```
   cd backend
   $env:DATABASE_URL="sqlite:///./app.db"
   uvicorn app.main:app --reload
   ```

That's it. No `python -m app.seed` needed — your vendors, dishes, and
orders are already in `app.db`, and the database upgrades itself on startup.

## When to start a fresh folder instead

Only if a release note says files were **deleted** (overwrite won't remove
old files). Then: fresh folder, full setup from README, and either copy
your `backend/app.db` into it or re-seed.

## v29 notes — reorder nudges + video uploads (Oct 2026)

### Reorder-nudge scheduler (optional — in-app send works regardless)

`GET /api/nudges` (logged-in accounts) lists dishes the customer ordered in
≥2 past orders whose most recent order is ≥21 days ago. To *push* those
nudges on a schedule, `POST /api/admin/nudges/send` (admin token required)
sends one Expo push per eligible dish to every customer that has push
tokens; `?dry_run=true` reports what would be sent without sending.

Hosting is on hold, so there is no scheduler running yet. When you're ready,
pick ONE on your host:

- **Windows Task Scheduler / cron**: `curl -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" https://your-host/api/admin/nudges/send`
  (e.g. weekly). Get the admin token by logging in as the admin once via
  `POST /api/auth/login`.
- **APScheduler in-process**: add a `BackgroundScheduler` in `backend/app/main.py`
  lifespan that POSTs to the same endpoint (needs the admin token in an env var).

The manual in-app send (vendor portal → Admin) works with zero setup.

### Video uploads directory

Dish videos and vendor intro videos live in
`frontend/img/uploads/videos/` — **user content, NOT shipped in the zips**
(the zip builder excludes `frontend/img/uploads/`). Because your `app.db`
and your uploads both live outside the zip, extracting a new version over
your existing folder keeps every video: nothing to back up, nothing to
re-upload. Videos are capped at 25 MB each (mp4/webm only) and uploads are
rate-limited per IP like dish photos.
