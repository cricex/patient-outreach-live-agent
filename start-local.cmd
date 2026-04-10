@echo off
REM start-local.cmd — Start backend + frontend for local development
REM Usage: double-click or run from project root

cd /d "%~dp0"

echo Starting Live Voice Agent Studio (local dev)...
echo.

REM Start backend (uvicorn on port 8000)
echo [1/2] Starting backend on http://localhost:8000 ...
start "VoiceAgent-Backend" cmd /k ".venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

REM Give backend a moment to start
timeout /t 3 /nobreak >nul

REM Start frontend dev server (Vite on port 5173)
echo [2/2] Starting frontend on http://localhost:5173 ...
start "VoiceAgent-Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo Both servers starting. Open http://localhost:5173 in your browser.
echo Close the terminal windows to stop the servers.
echo.
pause
