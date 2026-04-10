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

## Branching
- `v1` — frozen snapshot of pre-refactor codebase
- `v2` — active working branch (all Phase 1+ work)
- `main` — merge target when v2 is ready

## Log

<!-- Entries prepended newest-first -->
- **23:45 UTC** — Created `v1` branch (preserves v1 at `bdb632f`), switched to `v2` branch
- **23:40 UTC** — ✅ `p1-config` done — config.py rebuilt (removed 8 legacy fields, added 7 GA fields)
- **23:38 UTC** — ✅ `p1-structure` done — directories created (routers/, services/, models/, data/prompts/)
- **23:37 UTC** — ✅ `p1-deps` done — requirements.txt pinned (voicelive==1.1.0, added azure-identity)
- **23:36 UTC** — Wave 1 dispatched (p1-structure, p1-config, p1-deps)
- **23:35 UTC** — Phase 1 started, progress log created
