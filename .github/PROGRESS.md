# Phase 1 — Foundation Refactor Progress

> Auto-updated as work progresses. Each entry includes timestamp, task ID, and outcome.

## UX Fixes

| Task | Status | Notes |
|------|--------|-------|
| Phone number input E.164 fix | ✅ | Auto-strips non-digit chars (except leading +), `type="tel"`, placeholder `+15551234567`, helper label. `CallControls.tsx` — 2025-07-17 |
| Waveform display realism fix | ✅ | Backend emits `audio.rms` events with real PCM RMS levels (caller every ~100ms, agent per frame). Frontend uses `audio.rms` instead of frame-count events. WaveformDisplay renders centered mirrored bars with jitter for natural look. `speech.py`, `DiagnosticsPanel.tsx`, `WaveformDisplay.tsx` — 2025-07-24 |

## Status Legend
✅ Done | 🔄 In Progress | ⏳ Pending | ❌ Failed | 🚫 Blocked

---

## Wave 1 (parallel — no dependencies)

| Task | Status | Notes |
|------|--------|-------|
| `p1-structure` — Create directories | ✅ | `app/routers/`, `app/services/`, `app/models/`, `data/prompts/` |
| `p1-config` — Update config.py | ✅ | Removed 8 legacy fields, added 7 GA fields, clean validators |
| `p1-deps` — Update requirements.txt | ✅ | Pin `azure-ai-voicelive==1.1.0`, add `azure-identity` |

## Wave 2 (after structure)

| Task | Status | Notes |
|------|--------|-------|
| `p1-models` — Build data models | ✅ | `CallState`, `VoiceLiveState`, `MediaMetrics`, `AppState` (async), Pydantic request models |

## Wave 3 (after models + deps)

| Task | Status | Notes |
|------|--------|-------|
| `p1-speech` — Voice Live wrapper | ✅ | GA 1.1.0 SDK, ~200 lines (was ~400), native VAD/noise/echo/barge-in |
| `p1-media` — Media bridge service | ✅ | Decoupled (no circular imports), injectable deps, ~120 lines |

## Wave 4 (after speech + media)

| Task | Status | Notes |
|------|--------|-------|
| `p1-session` — CallSession class | ✅ | Per-call ownership of speech + timeouts, hangup via Future |

## Wave 5 (after session)

| Task | Status | Notes |
|------|--------|-------|
| `p1-manager` — CallManager | ✅ | Singleton orchestrator, get_speech() accessor, hangup future pattern |

## Wave 6 (after manager + config)

| Task | Status | Notes |
|------|--------|-------|
| `p1-routers` — Route handlers | ✅ | 3 files: calls.py, diagnostics.py, media.py — thin delegation |

## Wave 7 (after routers)

| Task | Status | Notes |
|------|--------|-------|
| `p1-main` — Rebuild main.py | ✅ | 368 → 53 lines, app factory + router mounting only |

## Wave 8 (after main)

| Task | Status | Notes |
|------|--------|-------|
| `p1-cleanup` — Remove legacy files | ✅ | Deleted back.env, voice_live.py, speech_session.py, media_bridge.py, state.py |

## Wave 9 (after cleanup)

| Task | Status | Notes |
|------|--------|-------|
| `p1-verify` — Smoke test | ✅ | 17 files parse, 0 IDE errors, app loads (11 routes), no stale refs |

## Wave 10 (after verify)

| Task | Status | Notes |
|------|--------|-------|
| `p1-docs` — Update instructions | ✅ | copilot-instructions.md fully rewritten for v2 architecture |

---

## Phase 2+3 — UI + Prompt Management + Live Diagnostics

### Wave 1 (parallel — no dependencies)

| Task | Status | Notes |
|------|--------|-------|
| `p2-prompt-store` — Backend prompt store | ✅ | JSON CRUD + example colonoscopy prompt |
| `p3-event-bus` — Diagnostic event bus | ✅ | Async pub/sub, 16 event types, recent buffer |
| `p2-react-scaffold` — React + Vite scaffold | ✅ | Vite + React + TS + Tailwind v4, proxy, types, API client, WS hook |

### Wave 2 (after services ready)

| Task | Status | Notes |
|------|--------|-------|
| `p2-api-router` — /api/ REST endpoints | ✅ | 5 endpoints: prompt CRUD + generation placeholder |
| `p3-diag-router` — /ws/ WebSocket endpoints | ✅ | /ws/diagnostics + /ws/call-status, mounted in main.py |
| `p3-wire-events` — Wire event bus into services | ✅ | 10 event types wired across speech.py, call_session.py, call_manager.py |

### Wave 3 (after scaffold + routers)

| Task | Status | Notes |
|------|--------|-------|
| `p2-config-panel` — Config + prompt UI | ✅ | PromptEditor + App.tsx rewritten to 40/60 single-page layout |
| `p2-call-controls` — Call controls UI | ✅ | Phone, voice, model, simulate, start/hangup, live status pill |
| `p3-diagnostics-ui` — Diagnostics panel | ✅ | WaveformDisplay (canvas), EventLog, MetricsBar, DiagnosticsPanel composite |

### Wave 4 (integration)

| Task | Status | Notes |
|------|--------|-------|
| `p2p3-integrate` — Static serving + verification | ⏳ | FastAPI serves React build, end-to-end test |

---

## Branching
- `v1` — frozen snapshot of pre-refactor codebase
- `v2` — active working branch (all Phase 1+ work)
- `main` — merge target when v2 is ready

## Log

<!-- Entries prepended newest-first -->
- **2025-07-25 UTC** — Auth security hardening (6 fixes): (1) Middleware returns 401 JSONResponse instead of raising HTTPException/500. (2) Removed dead WebSocket code from middleware; added `_ws_auth()` guard in `ws.py` before `accept()`. (3) Auth fails-closed — `_auth_enabled` flag; no env var = auth disabled, `DEMO_PASSWORDS=` empty = rejects all. (4) `data/calls/*.json` added to `.gitignore`, tracked files unstaged. (5) Static/SPA paths exempted via `_is_public()` (assets, root, static file extensions). (6) Session tokens — `create_session_token()` returns opaque `secrets.token_urlsafe`; raw passwords never leave the `/auth/validate` endpoint. Frontend stores token, WS sends token. `conftest.py` pops DEMO_PASSWORDS so tests run with auth disabled.
- **2025-07-25 UTC** — Shared-password auth gate: `app/auth.py` (Key Vault + env fallback), `AuthMiddleware` on all routes (except /health, /auth/validate, /call/events), `POST /auth/validate` endpoint, `LoginScreen.tsx` frontend gate, `client.ts` sends `X-Auth-Token` header + 401 handling, `useWebSocket.ts` token query param, `azure-keyvault-secrets` added to requirements. Tests disabled auth via `DEMO_PASSWORDS=""` in conftest. 30/30 tests passing, tsc + vite build clean.
- **2025-07-20 UTC** — Added 7 resampling unit tests (`tests/test_resample.py`): downsample/upsample sample counts, roundtrip length, int16 range, empty/tiny input. Full suite 30/30 passing.
- **2025-07-19 UTC** — Env diagnostics: all config values valid (ACS conn str, phone numbers, APP_BASE_URL HTTPS, VL endpoint/key/model). ACS client creates OK. Voice Live connect+session.update OK. Root cause of 502: `aiohttp` missing from requirements.txt (needed by `azure-ai-voicelive.aio`). Fixed: added `aiohttp>=3.9.0` to requirements.txt. Also installed missing `azure-identity` in local venv.
- **2026-07-12 UTC** — HTTPS tunnel: reused `swift-hill-t9dzp4x` devtunnel (port 8000/http, anonymous access), public URL `https://n3st3xsb-8000.usw2.devtunnels.ms`, updated `.env.local` with `APP_BASE_URL`, tunnel hosting as background process (PID 30964)
- **2025-07-18 19:30 UTC** — First Azure deployment: Bicep provisioned (Container Apps Environment, ACR, Key Vault, Log Analytics, managed identity), Docker image pushed to voiceagentdevacr.azurecr.io, Container App live at https://voiceagent-dev-app.ambitiouspond-82878311.eastus2.azurecontainerapps.io — /health and /status verified
- **2026-04-10 13:45 UTC**— GitHub Actions CI/CD: ci.yml (pytest + frontend lint/build on push/PR), deploy.yml (Docker → ACR → Container Apps on merge to main)
- **2026-04-10 13:40 UTC** — Bicep infrastructure: infra/main.bicep (Container Apps, ACR, Key Vault, Log Analytics, managed identity, RBAC) + main.bicepparam. Validated with az bicep build.
- **2026-04-10 13:35 UTC** — Docker: multi-stage Dockerfile (node:20-alpine → python:3.12-slim), .dockerignore, docker-compose.yml
- **2026-04-10 13:32 UTC** — Pytest test suite: 23 tests across 5 files (health, prompt CRUD, event bus, simulate call). Added pytest + pytest-asyncio.
- **2026-04-10 12:30 UTC** — v1 cleanup: deleted 8 stale files, rewrote README.md for v2
- **01:40 UTC** — UI polish committed: mockup-aligned layout, diagnostics overlay toggle, demo mode for preview without backend
- **01:25 UTC** — Call history committed (`6be4d81`): transcripts, ACS recording, /api/calls endpoints
- **01:10 UTC** — Comprehensive copilot-instructions.md rewrite (covers all P1-P3 + AI gen)
- **00:50 UTC** — AI prompt generation committed (`a87b036`): inference service, meta-prompt, prior-auth scenario
- **00:41 UTC** — Phase 2+3 committed (`05def4f`), starting AI prompt generation feature
- **00:25 UTC** — Wave 3 dispatched (config panel, call controls, diagnostics panel)
- **00:15 UTC** — Wave 2 complete (api router, diag router, event wiring)
- **00:10 UTC** — Wave 1 complete (prompt store, event bus, React scaffold)
- **23:40 UTC** — ✅ `p1-config` done — config.py rebuilt (removed 8 legacy fields, added 7 GA fields)
- **23:38 UTC** — ✅ `p1-structure` done — directories created (routers/, services/, models/, data/prompts/)
- **23:37 UTC** — ✅ `p1-deps` done — requirements.txt pinned (voicelive==1.1.0, added azure-identity)
- **23:36 UTC** — Wave 1 dispatched (p1-structure, p1-config, p1-deps)
- **23:35 UTC** — Phase 1 started, progress log created

- **2026-04-10 13:34 UTC** — ✅ CI/CD workflows created: `ci.yml` (test + lint on push/PR) and `deploy.yml` (Docker build + Container Apps deploy on main)
