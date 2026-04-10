# Copilot Instructions — Live Voice Agent Studio (v2)

## When working on implementation tasks:
1. Start with a concrete implementation plan.
2. Match existing repository patterns and keep changes tightly scoped.
3. Prefer /fleet only when workstreams are truly independent.
4. Rejoin with a final integration pass.
5. Run relevant build, test, lint, and type checks before finishing when available.
6. If anything cannot be validated, state the gap and risk clearly.
7. Always update .github/PROGRESS.md with a timestamped log of what was completed.


> Realtime voice agent demo platform using Azure Communication Services (ACS) and Azure AI Voice Live. Supports any industry — healthcare patient outreach, prior authorization, insurance, legal, retail, and more. **Not HIPAA-compliant — synthetic data only.**

## Run commands

```bash
# Load environment (merge .env + .env.local into current shell)
source scripts/load_env.sh

# Start the FastAPI backend
./scripts/start.sh   # uvicorn on Windows, gunicorn on Unix

# Start the React frontend dev server (separate terminal)
cd frontend && npm run dev   # Vite on http://localhost:5173, proxies to :8000

# Build frontend for production (FastAPI serves the built files)
cd frontend && npm run build

# Simulate a call (no PSTN, no ACS)
curl -X POST "$APP_BASE_URL/call/start" \
  -H "Content-Type: application/json" \
  -d '{"simulate": true}'

# Monitor
./scripts/poll_status.sh        # polls GET /status every 5s
tail -f logs/app.log            # structured logs
```

The backend listens on `${WEBSITES_PORT:-8000}`. The frontend dev server runs on `5173` with Vite proxy. An HTTPS tunnel (devtunnel) is required for ACS callbacks when running locally — see `STARTUP.md`.

No tests, linting, or CI pipelines exist yet.

## Architecture

```
                              [React UI (Vite + Tailwind)]
                               40/60 split layout
                               PromptEditor | CallControls
                               WaveformDisplay | DiagnosticsPanel
                                        │
                    ┌── REST (/api/*) ───┤── WS (/ws/*) ──────────────┐
                    │                    │                              │
             [FastAPI App Factory]  [/ws/diagnostics]          [/ws/call-status]
              main.py (~50 lines)   event streaming             status polling
              mounts 5 routers      via EventBus                via AppState
                    │
    ┌───────────────┼───────────────────────────────┐
    │               │               │               │
routers/        routers/       routers/         routers/
calls.py        api.py         diagnostics.py   media.py
/call/*         /api/prompts   /health          /media/{token} WS
                /api/prompts   /status
                /generate      /acs/health
    │               │                               │
    ▼               ▼                               ▼
[CallManager]   [PromptStore]              [media_bridge handler]
singleton       JSON CRUD                  get_speech callable (DI)
    │           [InferenceService]          concurrent in/out loops
    │           Foundry chat completions        │
    ▼                                           │
[CallSession (per-call)]                        │
    ├── SpeechService (Voice Live 1.1.0)  ◄─────┘
    ├── timeout watcher (Future)
    └── EventBus publishing
```

**Key endpoints:**

| Endpoint | Method | Router | Purpose |
|----------|--------|--------|---------|
| `/health` | GET | `diagnostics` | Liveness probe |
| `/status` | GET | `diagnostics` | Runtime snapshot (call, VL session, media metrics) |
| `/call/start` | POST | `calls` | Initiate outbound call or simulate |
| `/call/hangup` | POST | `calls` | Terminate active call |
| `/call/events` | POST | `calls` | ACS webhook receiver |
| `/media/{token}` | WS | `media` | ACS ↔ Voice Live audio bridge |
| `/acs/health` | GET | `diagnostics` | TLS diagnostics (DNS, cert, cipher) |
| `/api/prompts` | GET/POST/DELETE | `api` | Prompt set CRUD |
| `/api/prompts/generate` | POST | `api` | AI-powered scenario generation (Foundry) |
| `/ws/diagnostics` | WS | `ws` | Real-time diagnostic event stream |
| `/ws/call-status` | WS | `ws` | Polling call state every 1s |
| `/` | GET | `main` | Serve React frontend (production build) |

## Module guide

### `app/` — Core

| Module | Role |
|--------|------|
| `main.py` | FastAPI app factory (~50 lines). Mounts 5 routers, serves React static build, logs SDK versions on startup |
| `config.py` | Pydantic `Settings` model with env loading. Required fields validated. Voice Live GA features (noise reduction, echo cancellation, VAD). Foundry inference config (optional) |
| `logging_config.py` | RotatingFileHandler to `logs/app.log` + console. Format: `%(asctime)s %(levelname).1s %(name)s %(message)s` |
| `_ssl_patch.py` | TLS 1.3 workaround, imported first via `__init__.py` |

### `app/routers/` — Route Handlers (thin delegation)

| Module | Routes |
|--------|--------|
| `calls.py` | `/call/start`, `/call/hangup`, `/call/events` → delegates to `CallManager` |
| `diagnostics.py` | `/health`, `/status`, `/acs/health` → reads `AppState` |
| `media.py` | `/media/{token}` WS → wires `call_manager.get_speech` into `media_bridge` |
| `api.py` | `/api/prompts` CRUD → `PromptStore`; `/api/prompts/generate` → `InferenceService` |
| `ws.py` | `/ws/diagnostics` → subscribes to `EventBus`; `/ws/call-status` → polls `AppState` |

### `app/services/` — Business Logic

| Module | Role |
|--------|------|
| `call_manager.py` | Singleton orchestrating call lifecycle. Creates/destroys `CallSession`, exposes `get_speech()` for media bridge. Publishes `CALL_STARTED`/`CALL_ENDED` events |
| `call_session.py` | Per-call object owning `SpeechService` + timeout watcher (Future-based). Publishes `VL_SESSION_STARTED`/`ENDED` events |
| `speech.py` | Voice Live GA 1.1.0 wrapper. Native noise suppression, echo cancellation, barge-in, VAD. Publishes transcript, audio, and error events to EventBus |
| `media_bridge.py` | WebSocket media handler. Dependency-injected via `get_speech` callable (no circular imports). Concurrent inbound/outbound loops |
| `prompt_store.py` | JSON file CRUD for saved prompt sets in `data/prompts/`. `list_prompts()`, `get_prompt()`, `save_prompt()`, `delete_prompt()` |
| `event_bus.py` | Async pub/sub for diagnostic events. 16 event types, per-subscriber `asyncio.Queue`, 50-event recent buffer for late joiners |
| `inference.py` | Azure AI Foundry `ChatCompletionsClient` wrapper for AI scenario generation. Reads meta-prompt from `prompts/meta_generate.md` |

### `app/models/` — Data Models

| Module | Role |
|--------|------|
| `state.py` | `CallState`, `VoiceLiveState`, `MediaMetrics` dataclasses + `AppState` singleton (async-native with `asyncio.Lock`) |
| `requests.py` | Pydantic request/response models: `StartCallRequest`, `StartCallResponse`, `HangupResponse`, `CallEventsResponse` |

### `frontend/` — React UI

| Path | Role |
|------|------|
| `src/App.tsx` | Single-page 40/60 split layout. Scenario title in header, PromptEditor left, CallControls + DiagnosticsPanel right |
| `src/components/PromptEditor.tsx` | Scenario selector, system prompt + call brief textareas, AI generation button, save/load/delete |
| `src/components/CallControls.tsx` | Phone input, voice/model selects, simulate toggle, start/hangup, live status pill |
| `src/components/DiagnosticsPanel.tsx` | Composite: wires WebSockets, manages audio levels + events + metrics |
| `src/components/WaveformDisplay.tsx` | Canvas-based dual-lane RMS waveform (caller blue / agent green), scrolling bars, driven by live audio events |
| `src/components/EventLog.tsx` | Scrolling timestamped event feed with emoji icons |
| `src/components/MetricsBar.tsx` | Frames in/out, session timer |
| `src/api/client.ts` | `fetchJSON` helper + `api` object for all backend endpoints |
| `src/hooks/useWebSocket.ts` | Auto-reconnecting WebSocket hook |
| `src/types/index.ts` | `PromptSet`, `StartCallRequest`, `CallStatus`, `DiagnosticEvent` |

**Frontend stack:** Vite + React + TypeScript + Tailwind CSS v4. Dev server proxies `/api`, `/call`, `/ws` to `localhost:8000`.

### `data/` — Persistent Data

| Path | Content |
|------|---------|
| `data/prompts/*.json` | Saved prompt sets (scenario configs). Ships with `colonoscopy-outreach.json` and `prior-auth-neuro.json` |

### `prompts/` — Prompt Templates

| File | Purpose |
|------|---------|
| `system.md` | System prompt template with parameter placeholders |
| `call_brief.md` | CALL_BRIEF format specification and field reference |
| `care_detection.md` | Offline LLM prompt for generating CALL_BRIEF from clinical notes |
| `meta_generate.md` | Meta-prompt for AI scenario generation. Industry-agnostic — infers domain, regulatory context, identifiers, and call conventions from user's description |

## Configuration system

**Env file layering** (`.env` → `.env.local`, last wins):
- `scripts/load_env.sh` merges files into the current shell
- `config.py` calls `load_dotenv()` / `load_dotenv(".env.local", override=True)` at import time

**Settings model** (`config.py`):
- Pydantic `BaseModel` with `load_settings()` factory using `os.getenv()`
- Required: `APP_BASE_URL`, `ACS_CONNECTION_STRING`, `ACS_OUTBOUND_CALLER_ID`
- Voice Live GA: `AZURE_VOICELIVE_ENDPOINT`, `VOICELIVE_MODEL`, `VOICELIVE_VOICE`, `AZURE_VOICELIVE_API_KEY`
- Voice Live features: `VOICELIVE_NOISE_REDUCTION`, `VOICELIVE_ECHO_CANCELLATION`, `VOICELIVE_VAD_THRESHOLD`, `VOICELIVE_VAD_PREFIX_PADDING_MS`, `VOICELIVE_VAD_SILENCE_DURATION_MS`
- Foundry inference (optional): `FOUNDRY_INFERENCE_ENDPOINT`, `FOUNDRY_INFERENCE_MODEL`, `FOUNDRY_INFERENCE_API_KEY`
- Full reference: `ENV.md`

## Diagnostic event system

The `EventBus` (`app/services/event_bus.py`) is the backbone for real-time UI updates. Services publish typed events, WebSocket handlers fan out to connected clients.

**Event types:**
- Call lifecycle: `call.started`, `call.ended`
- Voice Live: `vl.session.started`, `vl.session.ended`, `vl.session.ready`, `vl.error`
- Audio: `audio.inbound` (throttled every 50 frames), `audio.outbound`, `audio.rms`, `audio.barge_in`
- Conversation: `transcript.user`, `transcript.agent`
- Media: `media.connected`, `media.disconnected`
- Tools (Phase 6): `tool.call.started`, `tool.call.completed`

**Wiring:** `speech.py` publishes transcript/audio/barge-in/error events. `call_session.py` publishes VL lifecycle. `call_manager.py` publishes call lifecycle and clears the event buffer on call end.

## Code conventions

### Every module starts with
```python
from __future__ import annotations
```

### Logger naming
```python
logger = logging.getLogger("app.main")      # main.py
logger = logging.getLogger("app.media")     # media_bridge.py
logger = logging.getLogger("app.voice")     # speech.py
logger = logging.getLogger("app.call")      # call_manager.py, call_session.py
logger = logging.getLogger("app.config")    # config.py
logger = logging.getLogger("app.prompts")   # prompt_store.py
logger = logging.getLogger("app.events")    # event_bus.py
logger = logging.getLogger("app.inference") # inference.py
logger = logging.getLogger("app.api")       # api.py router
logger = logging.getLogger("app.ws")        # ws.py router
```

### Type annotations — PEP 604
```python
_speech: SpeechService | None = None
async def connect(self, system_prompt: str | None) -> None: ...
```

### Error handling tiers
- **Operational** (frame send, hangup): `try/except → log warning → continue`
- **Initialization** (Voice Live, ACS SDK): `try/except → log error → raise`
- **Azure SDK**: catch `AzureError`, extract TLS diagnostics

### Async patterns
- All endpoints `async def`
- Blocking SDK calls in `loop.run_in_executor(None, ...)`
- State mutations via `asyncio.Lock` (not `threading.RLock`)
- Timeout watcher sets `asyncio.Future`; `CallManager` watches and cleans up

### Dependency injection
- Media bridge receives `get_speech` callable (no circular imports)
- `CallManager.get_speech()` returns active `SpeechService` or `None`

### Commenting style
- Comments explain **why**, not what
- PEP 257 docstrings on public APIs
- Tags: `TODO`, `FIXME`, `NOTE` — remove when resolved

## Key dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.111.0 | Web framework, WebSocket, route handlers |
| `uvicorn` | 0.30.0 | ASGI server (Windows) |
| `gunicorn` | 22.0.0 | Process manager (Unix) |
| `pydantic` | 2.7.3 | Settings validation, request models |
| `python-dotenv` | 1.0.1 | Env file parsing |
| `httpx` | 0.28.1 | Async HTTP client |
| `azure-communication-callautomation` | 1.5.0 | ACS Call Automation SDK |
| `azure-core` | 1.35.1 | Azure SDK foundation |
| `azure-identity` | ≥1.15.0 | Entra ID authentication |
| `azure-ai-voicelive` | 1.1.0 | Voice Live GA SDK |
| `azure-ai-inference` | ≥1.0.0 | Foundry chat completions (prompt generation) |

Frontend: React 19 + Vite + TypeScript + Tailwind CSS v4.

Python 3.10+ required.

## Project documentation

| File | Content |
|------|---------|
| `README.md` | Project overview (needs v2 update) |
| `ENV.md` | Env variable reference (needs v2 update) |
| `STARTUP.md` | Local dev setup: devtunnel, startup, troubleshooting |
| `.github/PROGRESS.md` | Build progress log with timestamps |
| `.github/UI_MOCKUP_PROMPT.md` | Image generation prompt for UI mockup |
| `prompts/` | System prompt, call brief, care detection, meta generation templates |
