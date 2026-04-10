# Phase 1 — Foundation Refactor Progress

> Auto-updated as work progresses. Each entry includes timestamp, task ID, and outcome.

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
