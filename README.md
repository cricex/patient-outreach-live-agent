# Live Voice Agent Studio

> Realtime voice agent demo platform using Azure Communication Services (ACS) and Azure AI Voice Live. Supports any industry — healthcare patient outreach, prior authorization, insurance, legal, retail, and more. **Not HIPAA-compliant — synthetic data only.**

---

## What it does

- Places outbound PSTN calls via ACS and bridges audio to Azure AI Voice Live in real time
- Voice Live performs STT → multimodal reasoning → TTS end-to-end (no separate Azure OpenAI hop)
- React UI for scenario authoring, call controls, and live diagnostics
- AI-powered prompt generation — describe a scenario in plain language and the system writes the full system prompt + call brief
- Ships with example scenarios (colonoscopy outreach, prior authorization)

---

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

### Key endpoints

| Endpoint | Method | Router | Purpose |
|----------|--------|--------|---------|
| `/health` | GET | diagnostics | Liveness probe |
| `/status` | GET | diagnostics | Runtime snapshot (call, VL session, media metrics) |
| `/call/start` | POST | calls | Initiate outbound call or simulate |
| `/call/hangup` | POST | calls | Terminate active call |
| `/call/events` | POST | calls | ACS webhook receiver |
| `/media/{token}` | WS | media | ACS ↔ Voice Live audio bridge |
| `/acs/health` | GET | diagnostics | TLS diagnostics (DNS, cert, cipher) |
| `/api/prompts` | GET/POST/DELETE | api | Prompt set CRUD |
| `/api/prompts/generate` | POST | api | AI-powered scenario generation |
| `/ws/diagnostics` | WS | ws | Real-time diagnostic event stream |
| `/ws/call-status` | WS | ws | Polling call state every 1s |
| `/` | GET | main | Serve React frontend (production build) |

---

## Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend development)
- Azure subscription with:
  - **Azure Communication Services** resource + purchased outbound phone number
  - **Azure AI Voice Live** resource (GA, with access to the realtime model)
  - **Azure AI Foundry** endpoint (optional, for AI prompt generation)
- HTTPS tunnel for local development (devtunnel, ngrok, etc.) — required for ACS callbacks

---

## Quick start

```bash
# Clone and install backend
git clone <repository-url>
cd <repository-directory>
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

# Configure environment
# 1. Copy .env and fill in your Azure credentials
# 2. Create .env.local with local overrides (APP_BASE_URL, LOG_LEVEL)

# Start the backend
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Start the frontend dev server (separate terminal)
cd frontend && npm install && npm run dev
# → http://localhost:5173 (proxies API calls to :8000)

# Build frontend for production (FastAPI serves the built files)
cd frontend && npm run build
```

### Simulate a call (no PSTN, no ACS)

Use the React UI at `http://localhost:5173` — toggle **Simulate** on, then click **Start Call**.

Or via curl:
```bash
curl -X POST http://localhost:8000/call/start \
  -H "Content-Type: application/json" \
  -d '{"simulate": true}'
```

---

## Environment variables

Configuration is loaded via `python-dotenv` with layered files: `.env` → `.env.local` (last wins). All values are consumed by the `Settings` model in `app/config.py`.

### Required

| Variable | Env name | Description |
|----------|----------|-------------|
| App base URL | `APP_BASE_URL` | Public HTTPS URL reachable by ACS (tunnel for local dev) |
| ACS connection string | `ACS_CONNECTION_STRING` | Full connection string with access key. No quotes. |
| ACS caller ID | `ACS_OUTBOUND_CALLER_ID` | E.164 phone number owned in ACS |

### Voice Live (required for real calls)

| Variable | Env name | Default | Description |
|----------|----------|---------|-------------|
| Endpoint | `AZURE_VOICELIVE_ENDPOINT` | — | Voice Live resource URL |
| API key | `AZURE_VOICELIVE_API_KEY` | — | Omit only if using Entra ID auth |
| API version | `AZURE_VOICELIVE_API_VERSION` | `2025-10-01` | Override for preview APIs |
| Model | `VOICELIVE_MODEL` | — | GA realtime model name (e.g. `gpt-realtime`) |
| Voice | `VOICELIVE_VOICE` | — | Voice ID (e.g. `alloy`, `sage`) |
| System prompt | `VOICELIVE_SYSTEM_PROMPT` | — | Optional prompt sent on VL session connect |
| Language hint | `VOICELIVE_LANGUAGE_HINT` | — | e.g. `en-US` |
| Wait for caller | `VOICELIVE_WAIT_FOR_CALLER` | `true` | Agent waits for callee greeting first |

### Voice Live audio processing (GA 1.1.0)

| Variable | Env name | Default | Description |
|----------|----------|---------|-------------|
| Noise reduction | `VOICELIVE_NOISE_REDUCTION` | `true` | Server-side noise suppression |
| Echo cancellation | `VOICELIVE_ECHO_CANCELLATION` | `true` | Server-side echo cancellation |
| VAD threshold | `VOICELIVE_VAD_THRESHOLD` | `0.5` | Speech detection probability (0.0–1.0) |
| VAD prefix padding | `VOICELIVE_VAD_PREFIX_PADDING_MS` | `300` | Audio kept before detected speech (ms) |
| VAD silence duration | `VOICELIVE_VAD_SILENCE_DURATION_MS` | `500` | Silence before end-of-turn (ms) |

### Foundry inference (optional — AI prompt generation)

| Variable | Env name | Default | Description |
|----------|----------|---------|-------------|
| Endpoint | `FOUNDRY_INFERENCE_ENDPOINT` | — | Azure AI Foundry endpoint |
| Model | `FOUNDRY_INFERENCE_MODEL` | `gpt-4o` | Chat completions model |
| API key | `FOUNDRY_INFERENCE_API_KEY` | — | Foundry API key |

### Call lifecycle

| Variable | Env name | Default | Description |
|----------|----------|---------|-------------|
| Call timeout | `CALL_TIMEOUT_SEC` | `90` | Hard max call duration (seconds) |
| Idle timeout | `CALL_IDLE_TIMEOUT_SEC` | `90` | Idle timeout (defaults to call timeout) |
| Call recording | `ENABLE_CALL_RECORDING` | `false` | Enable ACS call recording |

### Media bridge

| Variable | Env name | Default | Description |
|----------|----------|---------|-------------|
| Bidirectional | `MEDIA_BIDIRECTIONAL` | `true` | Two-way media stream with ACS |
| Start at create | `MEDIA_START_AT_CREATE` | `true` | Begin media when call is created |
| Channel type | `MEDIA_AUDIO_CHANNEL_TYPE` | `mixed` | `mixed` (mono) or `unmixed` |
| Frame bytes | `MEDIA_FRAME_BYTES` | `640` | ACS frame size (20ms @ 16kHz mono PCM) |
| Frame interval | `MEDIA_FRAME_INTERVAL_MS` | `20` | Frame cadence |
| VL inbound | `MEDIA_ENABLE_VL_IN` | `true` | Forward caller audio to Voice Live |
| VL outbound | `MEDIA_ENABLE_VL_OUT` | `true` | Forward Voice Live audio to caller |

### Application

| Variable | Env name | Default | Description |
|----------|----------|---------|-------------|
| Log level | `LOG_LEVEL` | `INFO` | `DEBUG` for local diagnostics |
| Port | `WEBSITES_PORT` | `8000` | Backend listen port |
| Default prompt | `DEFAULT_SYSTEM_PROMPT` | (built-in) | Fallback system prompt |
| Target phone | `TARGET_PHONE_NUMBER` | — | Default callee (overridable per call) |

---

## Module guide

### `app/` — Core

| Module | Role |
|--------|------|
| `main.py` | FastAPI app factory (~50 lines). Mounts 5 routers, serves React static build, logs SDK versions on startup. |
| `config.py` | Pydantic `Settings` model with env loading. Voice Live GA features (noise reduction, echo cancellation, VAD). Foundry inference config. |
| `logging_config.py` | RotatingFileHandler to `logs/app.log` + console. |
| `_ssl_patch.py` | TLS 1.3 workaround, imported first via `__init__.py`. |

### `app/routers/` — Route handlers (thin delegation)

| Module | Routes |
|--------|--------|
| `calls.py` | `/call/start`, `/call/hangup`, `/call/events` → delegates to `CallManager` |
| `diagnostics.py` | `/health`, `/status`, `/acs/health` → reads `AppState` |
| `media.py` | `/media/{token}` WS → wires `call_manager.get_speech` into `media_bridge` |
| `api.py` | `/api/prompts` CRUD → `PromptStore`; `/api/prompts/generate` → `InferenceService` |
| `ws.py` | `/ws/diagnostics` → subscribes to `EventBus`; `/ws/call-status` → polls `AppState` |

### `app/services/` — Business logic

| Module | Role |
|--------|------|
| `call_manager.py` | Singleton orchestrating call lifecycle. Creates/destroys `CallSession`, exposes `get_speech()` for media bridge. |
| `call_session.py` | Per-call object owning `SpeechService` + timeout watcher (Future-based). |
| `speech.py` | Voice Live GA 1.1.0 wrapper. Native noise suppression, echo cancellation, barge-in, VAD. |
| `media_bridge.py` | WebSocket media handler. Dependency-injected via `get_speech` callable (no circular imports). |
| `prompt_store.py` | JSON file CRUD for saved prompt sets in `data/prompts/`. |
| `event_bus.py` | Async pub/sub for diagnostic events. 16 event types, per-subscriber queue, 50-event recent buffer. |
| `inference.py` | Azure AI Foundry `ChatCompletionsClient` wrapper for AI scenario generation. |
| `call_history.py` | Call transcript storage and ACS recording API integration. |

### `app/models/` — Data models

| Module | Role |
|--------|------|
| `state.py` | `CallState`, `VoiceLiveState`, `MediaMetrics` dataclasses + `AppState` singleton (async-native). |
| `requests.py` | Pydantic request/response models for the call API. |

### `frontend/` — React UI

| Path | Role |
|------|------|
| `src/App.tsx` | Single-page 40/60 split layout. Scenario title header, PromptEditor left, CallControls + DiagnosticsPanel right. |
| `src/components/PromptEditor.tsx` | Scenario selector, system prompt + call brief textareas, AI generation button, save/load/delete. |
| `src/components/CallControls.tsx` | Phone input, voice/model selects, simulate toggle, start/hangup, live status pill. |
| `src/components/DiagnosticsPanel.tsx` | Composite: wires WebSockets, manages audio levels + events + metrics. |
| `src/components/WaveformDisplay.tsx` | Canvas-based dual-lane RMS waveform (caller blue / agent green). |
| `src/components/EventLog.tsx` | Scrolling timestamped event feed with emoji icons. |
| `src/components/MetricsBar.tsx` | Frames in/out, session timer. |
| `src/api/client.ts` | `fetchJSON` helper + `api` object for all backend endpoints. |
| `src/hooks/useWebSocket.ts` | Auto-reconnecting WebSocket hook. |
| `src/types/index.ts` | TypeScript type definitions. |

Frontend stack: Vite + React 19 + TypeScript + Tailwind CSS v4. Dev server on port 5173 proxies `/api`, `/call`, `/ws` to `localhost:8000`.

### `data/` — Persistent data

| Path | Content |
|------|---------|
| `data/prompts/*.json` | Saved prompt sets (scenario configs) |
| `data/calls/` | Call history records |

### `prompts/` — Prompt templates

| File | Purpose |
|------|---------|
| `system.md` | System prompt template with parameter placeholders |
| `call_brief.md` | CALL_BRIEF format specification and field reference |
| `care_detection.md` | Offline LLM prompt for generating CALL_BRIEF from clinical notes |
| `meta_generate.md` | Meta-prompt for AI scenario generation (industry-agnostic) |

---

## Diagnostic event system

The `EventBus` is the backbone for real-time UI updates. Services publish typed events; WebSocket handlers fan out to connected clients.

**Event types:** `call.started`, `call.ended`, `vl.session.started`, `vl.session.ended`, `vl.session.ready`, `vl.error`, `audio.inbound`, `audio.outbound`, `audio.rms`, `audio.barge_in`, `transcript.user`, `transcript.agent`, `media.connected`, `media.disconnected`, `tool.call.started`, `tool.call.completed`

---

## Key dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.111.0 | Web framework, WebSocket, route handlers |
| `uvicorn` | 0.30.0 | ASGI server |
| `pydantic` | 2.7.3 | Settings validation, request models |
| `python-dotenv` | 1.0.1 | Env file parsing |
| `httpx` | 0.28.1 | Async HTTP client |
| `azure-communication-callautomation` | 1.5.0 | ACS Call Automation SDK |
| `azure-core` | 1.35.1 | Azure SDK foundation |
| `azure-identity` | ≥1.15.0 | Entra ID authentication |
| `azure-ai-voicelive` | 1.1.0 | Voice Live GA SDK |
| `azure-ai-inference` | ≥1.0.0 | Foundry chat completions |

Frontend: React 19 + Vite + TypeScript + Tailwind CSS v4.

---

## Safety & scope

- **Data:** Synthetic only. Production requires HIPAA controls, PHI minimization, and key management.
- **Consent:** Always open with identity and purpose, respect opt-outs.
- **Guardrails:** System prompt enforces call flow, tone, and scope.
- **Escalation:** No live transfer or clinical triage — direct callers to a human when needed.
- **Integrations:** No writes to EHR/FHIR/CRM. Scheduling is mocked.
