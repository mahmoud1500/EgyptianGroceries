"""One-shot database migrations: create tables + apply schema updates.

Run BEFORE starting the app workers (prod):

    cd backend
    python -m app.migrate

Workers start with SKIP_MIGRATIONS=1 so two workers never migrate
simultaneously (DBA P0-1: concurrent ensure_schema() runs race on
ALTER TABLE ADD COLUMN and the second worker crashes with
"column already exists" on Postgres).

Local dev: just start uvicorn — startup still migrates automatically
when SKIP_MIGRATIONS is unset (so the zip-upgrade flow keeps working).
"""
from . import models  # noqa: F401 — register models for create_all
from .database import Base, engine, ensure_schema


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    print("Migrations complete.")


if __name__ == "__main__":
    main()
