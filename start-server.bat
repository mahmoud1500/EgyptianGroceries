@echo off
REM Start the marketplace server — just double-click this file.
REM Uses the SQLite database file and auto-reload (save a file, refresh the browser).
set "DATABASE_URL=sqlite:///./app.db"
cd /d "%~dp0backend"
if exist "%~dp0.venv\Scripts\uvicorn.exe" (
    "%~dp0.venv\Scripts\uvicorn.exe" app.main:app --reload
) else (
    uvicorn app.main:app --reload
)
