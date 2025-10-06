# Environment reference

This guide captures every environment variable used by the GA Voice Live version of the app and explains where to put it. The runtime reads values through `scripts/load_env.sh`, which merges `.env`, `.env.local`, and any extra file you pass in that order. The loader prefers `python-dotenv` for robust parsing but automatically falls back to plain `source` if Python is missing.

## Layered env files

| File | Purpose |
| ---- | ------- |
| `.env` | Deployment baseline. Checked into Azure App Service/Container Apps configuration or shared quietly with your platform team. |
| `.env.local` | Local overrides for developers. Keep it minimal—only values that differ from `.env` (for example, your ngrok URL). |
| `.env.notebook` | Optional. Only required when running `notebook/notebook.ipynb` to generate synthetic `CALL_BRIEF` data. |

> **Tip:** Keep quotes out of `ACS_CONNECTION_STRING`. If your portal copy adds quotes, remove them so validation passes.

---

## Core Voice Live service settings

Set these in whichever file maps to your environment (for local runs that usually means `.env` + overrides in `.env.local`). All values are consumed by `app/config.py`.

| Variable | Required | Notes |
| -------- | :------: | ----- |
| `APP_BASE_URL` | Yes | Public https base URL that ACS can reach (ngrok for local, production host in Azure). Do **not** use `http://`. |
| `ACS_CONNECTION_STRING` | Yes | Full ACS connection string with access key. No quotes. |
| `ACS_OUTBOUND_CALLER_ID` | Yes | E.164 phone number you own in ACS. |
| `TARGET_PHONE_NUMBER` | No | Default callee. Can be overridden per request. |
| `AZURE_VOICELIVE_ENDPOINT` | Yes | Voice Live resource endpoint (https://<resource>.cognitiveservices.azure.com/). |
| `AZURE_VOICELIVE_API_KEY` | Yes* | API key for Voice Live. Omit when authenticating with Entra ID instead. |
| `AZURE_VOICELIVE_API_VERSION` | No | Override only if you need a preview API. Defaults to GA `2025-10-01`. |
| `VOICELIVE_MODEL` | Yes | GA realtime model name (for example `gpt-realtime`). |
| `VOICELIVE_VOICE` | Yes | Voice Live voice ID (for example `alloy`). |
| `DEFAULT_SYSTEM_PROMPT` | No | Global fallback prompt if the caller payload omits one. Plain text only. |
| `VOICELIVE_SYSTEM_PROMPT` | No | Optional alternate prompt sent directly to the Voice Live session on connect. |
| `VOICELIVE_LANGUAGE_HINT` | No | Language hint for Voice Live (for example `en-US`). |
| `VOICELIVE_WAIT_FOR_CALLER` | No | `true` keeps the agent silent until the callee greets first. |
| `VOICELIVE_START_IMMEDIATE` | No | `true` starts media as soon as the WebSocket opens (skip ACS CallConnected wait). |
| `CALL_TIMEOUT_SEC` | No | Hard stop for a call (default 90). |
| `CALL_IDLE_TIMEOUT_SEC` | No | Idle-stop timer. Defaults to `CALL_TIMEOUT_SEC` if omitted. |
| `SPEECH_KEY` / `SPEECH_REGION` | No | Legacy Speech key/region. Only set when you still need fallback Speech APIs. |

---

## Local development overrides (`.env.local`)

The repository now ships an intentionally tiny `.env.local`:

```dotenv
APP_BASE_URL=
LOG_LEVEL=DEBUG
```

Populate `APP_BASE_URL` with the public https URL that tunnels back to your machine (for example the value ngrok prints). The blank default prevents accidental check-in of personal URLs.

`LOG_LEVEL` defaults to `INFO` inside the service; leaving it at `DEBUG` locally surfaces ACS + Voice Live timing details. Lower it back to `INFO` once you are done diagnosing latency.

Add other overrides only as needed. Any variable documented in the tables above/below can live in `.env.local`—the loader will layer it on top of `.env`.

---

## Advanced media & pacing knobs

You rarely need to touch these, but they are exposed for fine‑tuning conversational latency. Values shown are defaults.

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `MEDIA_BIDIRECTIONAL` | `true` | Maintain a bidirectional stream with ACS. Set `false` for one-way media experiments. |
| `MEDIA_START_AT_CREATE` | `true` | Begin media the moment ACS creates the call. Leave `true` for GA. |
| `MEDIA_AUDIO_CHANNEL_TYPE` | `mixed` | `mixed` (1x mono feed) or `unmixed` (separate caller/agent). |
| `MEDIA_FRAME_BYTES` | `640` | Expected ACS frame size (20 ms @ 16 kHz mono PCM). |
| `MEDIA_FRAME_INTERVAL_MS` | `20` | Frame cadence used by the pacer. |
| `MEDIA_OUT_FORMAT` | `json_simple` | Keep `json_simple` for GA Voice Live; `binary` remains for specialized labs. |
| `MEDIA_ENABLE_VL_IN` | `true` | Disable (`false`) to skip forwarding caller audio to Voice Live during experiments. |
| `MEDIA_ENABLE_VL_OUT` | `true` | Disable (`false`) to silence Voice Live responses (diagnostics only). |
| `VOICELIVE_UPSAMPLE_16K_TO_24K` | `true` | Upsamples ACS audio before streaming to Voice Live. |
| `VOICELIVE_INPUT_FLUSH_FRAMES` | `4` | Minimum 20 ms frames buffered before flushing input to Voice Live. |
| `VOICELIVE_INPUT_FLUSH_INTERVAL_MS` | `60` | Timer that forces a flush even if the frame target is not hit. |
| `VOICELIVE_INPUT_FLUSH_MAX_INTERVAL_MS` | `180` | Absolute cap in case the timer keeps getting deferred. Must be ≥ interval. |
| `DEBUG_VOICELIVE_INPUT_FLUSH` | `false` | Emits RMS telemetry for each flush—useful when tuning VAD. |

---

## Notebook-only variables (`.env.notebook`)

If you continue to use the optional preventive-care notebook, keep its credentials separate from the live service. The notebook still relies on Azure OpenAI to synthesize `CALL_BRIEF` text but never touches the GA call flow.

| Variable | Purpose |
| -------- | ------- |
| `NOTES_PATH` | Directory containing synthetic clinical notes. |
| `APP_BASE_URL` | HTTPS callback base the notebook passes to ACS. Use a publicly reachable tunnel (ngrok) or swap to the dummy https placeholder baked into the helper. |
| `AI_FOUNDRY_API_KEY` | Notebook-specific name for the Azure OpenAI key; the loader maps it to `AZURE_OPENAI_KEY`. |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint used only inside the notebook. |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Chat model deployment for `CALL_BRIEF` generation. |
| `AZURE_OPENAI_API_VERSION` | API version string required by the SDK/REST call. |
| `ACS_CONNECTION_STRING` | Minimal ACS access for the one-way playback demo. Same value as production `.env` is fine. |
| `ACS_OUTBOUND_CALLER_ID` | E.164 caller ID number registered to your ACS resource. |
| `TARGET_PHONE_NUMBER` | Default callee for notebook test calls. |
| `TTS_VOICE` | Neural voice name used by the playback helper. |
| `COGNITIVE_SERVICES_ENDPOINT` | Speech resource endpoint used for TTS synthesis. |

For optional experimentation, you can also layer in any of the Voice Live toggles documented above (for example `MEDIA_BIDIRECTIONAL`)—the loader will merge them the same way as the app runtime.

---

## Tooling helpers

| Variable | Purpose |
| -------- | ------- |
| `NGROK_AUTH_TOKEN` | Optional convenience token consumed by `scripts/ngrok_auth.sh` so each developer can run `ngrok` without re-entering credentials. |

---

## Using the loader

```bash
# Load env into the current shell (merge .env + .env.local)
source scripts/load_env.sh

# Optionally include an additional file last (highest precedence)
source scripts/load_env.sh .env.test
```

The script prints which files were sourced. If Python or `python-dotenv` is unavailable, it falls back to simple `source` semantics—so keep your env files free of shell expansions that you would not run manually.
