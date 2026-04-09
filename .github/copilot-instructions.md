# Copilot Instructions — Patient Outreach Live Agent

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
                                     [FastAPI Orchestrator]
                               (state, ACS webhooks, VL session)
                                              │
                  ┌────────────── Control (HTTP/Webhooks) ───────────────┐
                  │                                                      │
          [ACS Call Automation]                                 [Azure AI Voice Live]
          • POST /call/start (outbound)                         • WS session (gpt-realtime)
          • POST /call/events (webhooks)                        • instructions = CALL_BRIEF
                  │                                                      │
                  └──────────── Media (WebSocket, PCM 16k/16-bit) ───────┘
                                 ◄───── Media Bridge + Pacer ─────►
                        (20 ms frames; flush-target/interval/max-interval)
                                              │
                                          [Phone Call]
```

**Data flow for a live call:**
1. `POST /call/start` → ACS places PSTN call with media streaming enabled
2. ACS sends `CallConnected` + `MediaStreamingStarted` webhooks to `/call/events`
3. ACS opens WebSocket to `/media/{token}` — bidirectional 16 kHz PCM audio
4. FastAPI opens a Voice Live WebSocket session (STT → LLM reasoning → TTS, end-to-end)
5. `media_bridge.py` bridges audio: ACS frames → upsample 16→24 kHz → Voice Live input; Voice Live output → ACS frames
6. Input flush logic buffers N frames before committing to Voice Live (tunable via `VOICELIVE_INPUT_FLUSH_*` env vars)
7. Call ends via timeout, hangup, or ACS disconnect event

**Key endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Returns `"ok"` |
| `/status` | GET | Runtime snapshot: call state, Voice Live session, media frame counts, flush metrics |
| `/call/start` | POST | Initiate outbound call or simulate locally (`{"simulate": true}`) |
| `/call/hangup` | POST | Terminate active call |
| `/call/events` | POST | ACS webhook receiver (CallConnected, MediaStreamingStarted, CallDisconnected) |
| `/media/{token}` | WS | Bidirectional ACS ↔ Voice Live audio bridge |
| `/acs/health` | GET | ACS endpoint TLS diagnostics (DNS, cert, cipher) |

## Module guide (`app/`)

| Module | Role | Key exports |
|--------|------|-------------|
| `__init__.py` | Package init — imports `_ssl_patch` first (TLS 1.3 workaround, must load before Azure SDK) | — |
| `main.py` | FastAPI app, all route handlers, call lifecycle, global `_speech` session management, timeout watcher | `app` (FastAPI instance) |
| `config.py` | Pydantic `Settings` model, env loading with `python-dotenv`, validation | `settings` (singleton) |
| `state.py` | Thread-safe `AppState` with `RLock` — tracks call metadata, Voice Live session info, media metrics | `app_state` (singleton) |
| `speech_session.py` | `SpeechSession` class — wraps Azure AI Voice Live async SDK, manages connect/disconnect, event consumption, input flush timer, output audio queue | `SpeechSession` |
| `media_bridge.py` | WebSocket handler for `/media/{token}` — concurrent inbound/outbound loops, frame slicing, 16→24 kHz upsampling, flush gating | `handle_media_ws()` |
| `voice_live.py` | Legacy compatibility shim (thin wrapper) | — |
| `logging_config.py` | Configures root logger, `RotatingFileHandler` to `logs/app.log`, console handler | `setup_logging()` |
| `_ssl_patch.py` | Patches SSL context to allow TLS 1.3 with Azure endpoints | — |

**Dependency graph:**
```
main.py
  ├── config.py (settings)
  ├── logging_config.py
  ├── state.py (app_state)
  ├── speech_session.py
  │     ├── config.py
  │     ├── state.py
  │     └── azure.ai.voicelive.aio SDK
  └── media_bridge.py
        ├── config.py
        ├── state.py
        └── speech_session.py
```

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
logger = logging.getLogger("app.voice")   # speech_session.py
```
Log format: `%(asctime)s %(levelname).1s %(name)s %(message)s` (single-letter level).

### Type annotations
Python 3.10+ style with PEP 604 unions:
```python
_speech: SpeechSession | None = None
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
- Input flush timer uses `asyncio.sleep()` loop.

### State management
- `app_state` (state.py): Thread-safe singleton using `threading.RLock()`. Tracks call metadata, Voice Live session info, media counters. `.snapshot()` method returns a serializable dict for `/status`.
- `_speech` (main.py): Global `SpeechSession | None` — created on call start, destroyed on call end. Managed in route handlers and timeout watcher.

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
| `azure-ai-voicelive` | (unpinned) | Voice Live GA SDK (beta) |

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
