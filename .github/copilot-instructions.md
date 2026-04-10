# Copilot Instructions — Patient Outreach Live Agent (v2)

> Research PoC for preventive-care gap closure using Azure Communication Services (ACS) and Azure AI Voice Live. **Not HIPAA-compliant — synthetic data only.**

## Run commands

```bash
# Load environment (merge .env + .env.local into current shell)
source scripts/load_env.sh

# Start the FastAPI app
# Windows: uvicorn directly; Unix: gunicorn with UvicornWorker (2 workers)
./scripts/start.sh

# Trigger an outbound call (edit JSON in script to toggle simulate/target)
./scripts/make_call.sh

# Simulate locally (no PSTN, no ACS) — useful for exercising the Voice Live pipeline
curl -X POST "$APP_BASE_URL/call/start" \
  -H "Content-Type: application/json" \
  -d '{"simulate": true}'

# Monitor
./scripts/poll_status.sh        # polls GET /status every 5s
tail -f logs/app.log            # structured logs
```

The app listens on `${WEBSITES_PORT:-8000}`. An HTTPS tunnel (ngrok or devtunnel) is required for ACS callbacks when running locally — see `STARTUP.md`.

No tests, linting, or CI pipelines exist yet.

## Architecture

```
[Synthetic Notes] ──► [Notebook (optional)] ──► [CALL_BRIEF]
                                              │
                                              ▼
                                     [FastAPI App Factory]
                              (routers, startup, SDK version log)
                                              │
              ┌──── Routers ──────────────────┼──────────────────────────┐
              │                               │                          │
     routers/calls.py              routers/diagnostics.py       routers/media.py
     • /call/start                 • /health                    • /media/{token} WS
     • /call/hangup                • /status                         │
     • /call/events                • /acs/health                     │
              │                                                      │
              ▼                                                      ▼
     [CallManager singleton]                              [media_bridge handler]
     • orchestrates lifecycle                             • get_speech callable (DI)
     • owns CallSession                                   • concurrent in/out loops
              │                                                      │
              ▼                                                      │
     [CallSession (per-call)]                                        │
     • owns SpeechService                                            │
     • timeout watcher (Future)                                      │
     • state mutations                                               │
              │                                                      │
              ▼                                                      │
     [SpeechService]                                                 │
     • Voice Live GA 1.1.0 SDK                                       │
     • noise reduction, echo cancel                                  │
     • native barge-in, VAD                                          │
              │                                                      │
              └──────────── Media (WebSocket, PCM 16k/16-bit) ───────┘
                                              │
                                          [Phone Call]
```

**Data flow for a live call:**
1. `POST /call/start` → `CallManager` creates a `CallSession`, ACS places PSTN call with media streaming
2. ACS sends `CallConnected` + `MediaStreamingStarted` webhooks to `/call/events` → routed to `CallManager`
3. ACS opens WebSocket to `/media/{token}` — bidirectional 16 kHz PCM audio
4. `CallSession` opens a Voice Live session via `SpeechService` (STT → LLM reasoning → TTS, end-to-end)
5. `media_bridge.py` bridges audio between ACS and Voice Live — SDK handles upsampling and frame formatting natively
6. Call ends via timeout (Future-based watcher), hangup, or ACS disconnect event → `CallManager` cleans up `CallSession`

**Key endpoints:**

| Endpoint | Method | Router | Purpose |
|----------|--------|--------|---------|
| `/health` | GET | `diagnostics` | Returns `"ok"` |
| `/status` | GET | `diagnostics` | Runtime snapshot: call state, Voice Live session, media frame counts |
| `/call/start` | POST | `calls` | Initiate outbound call or simulate locally (`{"simulate": true}`) |
| `/call/hangup` | POST | `calls` | Terminate active call |
| `/call/events` | POST | `calls` | ACS webhook receiver (CallConnected, MediaStreamingStarted, CallDisconnected) |
| `/media/{token}` | WS | `media` | Bidirectional ACS ↔ Voice Live audio bridge |
| `/acs/health` | GET | `diagnostics` | ACS endpoint TLS diagnostics (DNS, cert, cipher) |

## Module guide (`app/`)

| Module | Role | Key exports |
|--------|------|-------------|
| `__init__.py` | Package init — imports `_ssl_patch` first (TLS 1.3 workaround, must load before Azure SDK) | — |
| `main.py` | FastAPI app factory (~50 lines). Mounts routers, logs SDK versions on startup | `app` (FastAPI instance) |
| `config.py` | Pydantic `Settings` model, env loading with `python-dotenv`, validation. Removed legacy fields (speech_key, flush timers, upsample); added GA features (noise_reduction, echo_cancellation, vad_threshold/prefix/silence) | `settings` (singleton) |
| `logging_config.py` | Configures root logger, `RotatingFileHandler` to `logs/app.log`, console handler | `setup_logging()` |
| `_ssl_patch.py` | Patches SSL context to allow TLS 1.3 with Azure endpoints | — |

### `app/routers/`

| Module | Role | Key exports |
|--------|------|-------------|
| `calls.py` | `/call/start`, `/call/hangup`, `/call/events` routes — thin delegation to `CallManager` | `router` |
| `diagnostics.py` | `/health`, `/status`, `/acs/health` routes | `router` |
| `media.py` | `/media/{token}` WebSocket route — wires `get_speech` callable into media bridge | `router` |

### `app/services/`

| Module | Role | Key exports |
|--------|------|-------------|
| `call_manager.py` | Singleton orchestrating call lifecycle. Replaces v1's global `_speech` and scattered ACS logic. Creates/destroys `CallSession`, exposes `get_speech()` callable for media bridge | `call_manager` (singleton) |
| `call_session.py` | Per-call object owning `SpeechService`, timeout watcher (Future-based), and state transitions. Created on call start, destroyed on call end | `CallSession` |
| `speech.py` | Voice Live GA 1.1.0 wrapper (~200 lines). No manual flush timers, no upsampling, no base64 — SDK handles all of it. Supports noise reduction (`AudioNoiseReduction`), echo cancellation (`AudioEchoCancellation`), configurable VAD | `SpeechService` |
| `media_bridge.py` | WebSocket media handler. Decoupled via dependency injection (`get_speech` callable, no circular imports). Concurrent inbound/outbound loops | `handle_media_ws()` |

### `app/models/`

| Module | Role | Key exports |
|--------|------|-------------|
| `state.py` | `CallState`, `VoiceLiveState`, `MediaMetrics` dataclasses + `AppState` singleton using `asyncio.Lock` (not `threading.RLock`) | `app_state` (singleton) |
| `requests.py` | Pydantic request/response models for API endpoints | — |

**Dependency graph (v2):**
```
main.py
  ├── routers/calls.py → services/call_manager.py
  ├── routers/diagnostics.py → models/state.py, config.py
  ├── routers/media.py → services/call_manager.py, services/media_bridge.py
  └── config.py, logging_config.py

services/call_manager.py
  ├── services/call_session.py
  │     └── services/speech.py → config.py, azure.ai.voicelive SDK
  ├── models/state.py (app_state singleton)
  └── ACS SDK (azure.communication.callautomation)

services/media_bridge.py
  ├── config.py (settings)
  └── models/state.py (AppState — injected)
  (NO circular imports — get_speech callable injected by caller)
```

### Deleted v1 files

These files no longer exist and should not be referenced:
- `app/speech_session.py` → replaced by `app/services/speech.py`
- `app/media_bridge.py` → replaced by `app/services/media_bridge.py`
- `app/state.py` → replaced by `app/models/state.py`
- `app/voice_live.py` → deleted (legacy shim)

## Configuration system

**Env file layering** (`.env` → `.env.local`, last wins):
- `scripts/load_env.sh` merges files into the current shell. Uses `python-dotenv` via `scripts/_load_env.py` for robust parsing; falls back to plain `source`.
- `config.py` also calls `load_dotenv()` / `load_dotenv(".env.local", override=True)` at import time.
- Add additional overlay files: `source scripts/load_env.sh .env.test`

**Settings model** (`config.py`):
- Pydantic `BaseModel` (not `BaseSettings`) — fields populated from `os.getenv()` in a `load_settings()` factory.
- Required fields (`app_base_url`, `acs_connection_string`, `acs_outbound_caller_id`) enforced via `@field_validator`.
- `validate_voicelive()` method checks Voice Live config consistency post-load.
- Boolean env vars: compare `.lower() == "true"`.
- `ACS_CONNECTION_STRING` has special quote-stripping logic.
- **v2 removals:** `speech_key`, `VOICELIVE_INPUT_FLUSH_*` timers, upsample settings.
- **v2 additions:** `noise_reduction`, `echo_cancellation`, `vad_threshold`, `vad_prefix`, `vad_silence`.

**Full env variable reference:** see `ENV.md`.

## Prompt architecture

Two layers steer the voice conversation:

1. **System prompt** — global guardrails for tone, privacy, call flow, scheduling rules, turn-taking behavior. Default in `DEFAULT_SYSTEM_PROMPT` env var. Can be overridden per-call via `POST /call/start` payload. The canonical template with parameter placeholders lives in `prompts/system.md`.

2. **CALL_BRIEF** — patient-specific context (top need, priority, timing, history, openers, scheduling starters). Produced offline by the notebook or precomputed upstream. Injected into the Voice Live session so the agent stays on-topic. Template and field reference in `prompts/call_brief.md`.

3. **Care detection prompt** — `prompts/care_detection.md` instructs an LLM to evaluate clinical notes and generate a CALL_BRIEF. Used only in offline notebook prep, not during live calls.

## Code conventions

### Every module starts with
```python
from __future__ import annotations
```
This enables PEP 604 union syntax (`str | None`) everywhere and avoids circular import issues with forward references.

### Logger naming
Hierarchical, module-based:
```python
logger = logging.getLogger("app.main")    # main.py
logger = logging.getLogger("app.media")   # media_bridge.py
logger = logging.getLogger("app.voice")   # speech.py
logger = logging.getLogger("app.call")    # call_manager.py, call_session.py
logger = logging.getLogger("app.config")  # config.py
```
Log format: `%(asctime)s %(levelname).1s %(name)s %(message)s` (single-letter level).

### Type annotations
Python 3.10+ style with PEP 604 unions:
```python
current_session: CallSession | None = None
async def connect(self, system_prompt: str | None) -> None: ...
async def get_next_outbound_frame(self) -> bytes | None: ...
```

### Error handling tiers
- **Operational errors** (frame send fails, hangup API fails): `try/except → log warning → continue`. Never crash the media loop.
- **Initialization errors** (Voice Live connect, ACS SDK): `try/except → log error → raise`. Propagate up.
- **Retry with fallback**: First attempt fails → sleep 0.5s → retry once → raise original error if still failing.
- **Azure SDK errors**: Catch `AzureError`/`ServiceRequestError`, extract TLS diagnostics (endpoint, host, cipher), log at ERROR level.

### Async patterns
- All FastAPI endpoints are `async def`.
- Blocking Azure SDK calls wrapped in `loop.run_in_executor(None, ...)` to avoid blocking the event loop.
- Media bridge runs concurrent `asyncio` tasks: one for inbound audio (ACS → Voice Live), one for outbound (Voice Live → ACS).
- Voice Live events consumed via async iterator in a background task.
- State mutations use `asyncio.Lock` (async-native, not `threading.RLock`).
- Timeout watcher sets an `asyncio.Future`; `CallManager` watches it and triggers cleanup.

### State management
- `app_state` (`models/state.py`): Async-safe singleton using `asyncio.Lock`. Contains `CallState`, `VoiceLiveState`, `MediaMetrics` dataclasses. `.snapshot()` method returns a serializable dict for `/status`.
- `CallManager.current_session` (`services/call_manager.py`): `CallSession | None` — replaces v1's global `_speech`. Per-call lifecycle managed by `CallManager`.
- **No globals for call state** — all call state is owned by `CallSession`, not scattered across module-level variables.

### Dependency injection
- Media bridge receives a `get_speech` callable from the router, not a direct import. This eliminates circular imports between services.
- `CallManager` exposes `get_speech()` which returns the current session's `SpeechService` or `None`.

### Commenting style
- Comments explain **why**, constraints, and side effects — not what the code does.
- Public functions/classes get PEP 257 docstrings with Args/Returns/Raises.
- Inline comments only when intent is non-obvious.
- Bash scripts: shebang, `set -euo pipefail`, brief header comment, usage block.
- Tags: `TODO`, `FIXME`, `NOTE` with actionable context. Remove when resolved.

## Key dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.111.0 | Async web framework, route handlers, WebSocket |
| `uvicorn` | 0.30.0 | ASGI server (Windows direct, Unix via gunicorn) |
| `gunicorn` | 22.0.0 | Process manager for Unix deploys |
| `pydantic` | 2.7.3 | Settings validation, request/response models |
| `python-dotenv` | 1.0.1 | Env file parsing |
| `httpx` | 0.28.1 | Async HTTP client |
| `azure-communication-callautomation` | 1.5.0 | ACS Call Automation SDK |
| `azure-core` | 1.35.1 | Azure SDK foundation |
| `azure-identity` | ≥1.15.0 | Entra ID authentication (new in v2) |
| `azure-ai-voicelive` | 1.1.0 | Voice Live GA SDK (pinned — was unpinned beta in v1) |

Python 3.10+ required (PEP 604 unions, `match` statements).

## Project documentation

| File | Content |
|------|---------|
| `README.md` | Full project overview, architecture diagram, API reference, tuning cheatsheet, troubleshooting |
| `ENV.md` | Complete env variable reference with defaults and layering explanation |
| `STARTUP.md` | Local dev setup: devtunnel config, step-by-step startup, troubleshooting table |
| `prompts/system.md` | System prompt template with parameter placeholders |
| `prompts/call_brief.md` | CALL_BRIEF format specification and field reference |
| `prompts/care_detection.md` | Offline LLM prompt for generating CALL_BRIEF from clinical notes |
