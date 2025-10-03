# Preventive Care Gap Closure – Azure Voice Live Outreach

> **What changed?** The preview hybrid (Voice Live + Azure OpenAI realtime) stack has been replaced with a **Voice Live GA-only** pipeline. All code now talks directly to Azure Communication Services (ACS) and Azure AI Voice Live, no secondary Azure OpenAI connection is required during calls.
>
> **HIPAA & production disclaimer:** This repository remains a research PoC. It is not HIPAA compliant, has not undergone threat modeling, and should not be used with real PHI without a full security/privacy review.

---

## Table of contents

1. [Scenario: What It Does and Why It Matters](#scenario-what-it-does-and-why-it-matters)
2. [Architecture](#architecture)
3. [Feature highlights](#feature-highlights)
4. [Prerequisites](#prerequisites)
5. [Install & configure](#install--configure)
6. [Quick start workflow](#quick-start-workflow)
7. [Calling API](#calling-api)
8. [Prompts](#prompts)
9. [Script toolbox](#script-toolbox)
10. [Observability](#observability)
11. [Tuning cheatsheet](#tuning-cheatsheet)
12. [Troubleshooting](#troubleshooting)
13. [Notebook (optional)](#notebook-optional)
14. [Safety, scope, non-goals](#safety-scope-non-goals)
15. [To do & roadmap](#to-do--roadmap)

---

## Scenario: What It Does and Why It Matters

### What it does

* Detects preventive care gaps from synthetic EHR like data such as mammogram or colonoscopy due
* Summarizes patient context in plain language as a `CALL_BRIEF`
* Calls the patient and runs a real time, **unscripted** multilingual conversation that

  * uses the patient specific `CALL_BRIEF` as context so responses stay on topic
  * explains the screening and answers common non clinical questions
  * provides basic procedure information
  * offers appointment times using a mocked scheduler
  * is powered end-to-end by **Azure Communication Services** and **Azure AI Voice Live** (no Azure OpenAI realtime hop required)

### Why it matters

* Clinical quality: More on time screenings improve early detection
* Operational impact: Lower cost outreach can recover reimbursable services
* Revenue impact: Increases completed preventive visits, captures quality incentives, supports value based contracts, and drives appropriate downstream services
* Equity: Native language conversations reduce access barriers

**Example dialog**
Unscripted conversation that uses the patient `CALL_BRIEF` for context and follows guardrails.

* **Patient:** Hello
* **Agent:** Hi, is this [Name]
* **Patient:** Yes
* **Agent:** Great. I am calling from [Clinic]. You are due for a mammogram. Your last one was in [Month YYYY]. Is it okay if we set that up now
* **Patient:** Sure
* **Agent:** It takes about 20 minutes. Do mornings or afternoons work better for you
* **Patient:** Afternoons
* **Agent:** I have Tuesday at 3:20 pm or Thursday at 1:40 pm at [Location]. Which do you prefer
* **Patient:** Thursday
* **Agent:** Perfect. You are set for Thursday at 1:40 pm at [Location]. I can text a reminder. Want that
* **Patient:** Yes
* **Agent:** Done. Bring a photo ID and your insurance card if you have one. If plans change, reply to the text or call [Number]. Have a good day


---

## Architecture

The FastAPI orchestrator places calls with ACS, receives call webhooks, opens a single Azure AI Voice Live (gpt-realtime) session per call, and bridges 20 ms PCM audio between ACS and Voice Live over WebSockets using a steady pacer and flush-timer gating. Voice Live performs STT → multimodal reasoning → TTS end-to-end, so there’s no separate Azure OpenAI hop. Observability is sidecar-style via structured logs and /status (frame counts, RTT, flush activity, errors).

```
[Synthetic Notes] ──► [Notebook (optional)] ──► [CALL_BRIEF]
                                              │
                                              ▼
                                     [FastAPI Orchestrator]
                               (state, ACS webhooks, VL session)
                                              │
                  ┌────────────── Control (HTTP/Webhooks) ───────────────┐
                  │                                                       │
          [ACS Call Automation]                                  [Azure AI Voice Live]
          • /call/start (outbound)                                • WS session (gpt-realtime)
          • /call/events webhooks                                 • instructions = CALL_BRIEF
                  │                                                       │
                  └──────────── Media (WebSocket, PCM 16k/16-bit) ────────┘
                                 ◄───── Media Bridge + Pacer ─────►
                        (20 ms frames; flush-target/interval/max-interval)
                                              │
                                          [Phone Call]
                                              │
                                              └──────────► [Logs & Metrics sidecar]
                                                           • /status (frames, RTT, flush: reason/targets)
                                                           • structured logs / traces / alerts

```

Key runtime endpoints:

* `POST /call/start` – initiate a call (real or simulated)
* `POST /call/events` – required ACS callback entry point
* `WS /media/{token}` – ACS media streaming bridge
* `GET /status` – live counters, timers, and call state snapshot

---

## Feature highlights

* **Azure Voice Live stack** – Azure AI Voice Live performs STT + multimodal reasoning + TTS end-to-end, no secondary Azure OpenAI hop required.
* **Outbound calling via ACS** – PSTN dial-outs with media streaming turned on by default.
* **Simulation mode** – Skip ACS entirely by sending `{ "simulate": true }` when exercising the bridge locally.
* **Configurable prompts** – Global defaults plus per-request overrides for target number and system prompt.
* **Input flush tuning** – Control buffer size and timers to balance responsiveness against VAD accuracy.
* **Rich diagnostics** – `/status`, structured logs, optional RMS telemetry for input flushes.

---

## Prerequisites

* Python 3.10+
* Azure subscription with:
  * Azure Communication Services resource + purchased outbound phone number
  * Azure AI Voice Live resource (and access to the GA realtime model you plan to use)
* `ngrok` (or an equivalent HTTPS tunnel) when running locally

---

## Install & configure

```bash
git clone <repository-url>
cd <repository-directory>

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

1. Copy your secrets into `.env` (deployment baseline).
2. Create `.env.local` with local overrides. Start from the two-line skeleton below and fill in your tunnel:

  ```dotenv
  APP_BASE_URL=
  LOG_LEVEL=DEBUG
  ```

  Add other variables only when you truly need to override the baseline—`scripts/load_env.sh` layers `.env.local` last.
3. Run `source scripts/load_env.sh` to merge them. The loader prefers `python-dotenv`; it falls back to plain `source` if Python is unavailable.
4. Review [ENV.md](ENV.md) for every supported variable and default.

---

## Quick start workflow

```bash
# 1) Load environment (merge .env + .env.local)
source scripts/load_env.sh

# 2) Start an HTTPS tunnel if you want ACS callbacks
./scripts/ngrok_tunnel.sh &

# 3) Launch the FastAPI app
./scripts/start.sh

# 4) Trigger a call (edit simulate flag inside the script or payload)
./scripts/make_call.sh

# 5) Watch status and logs
./scripts/poll_status.sh
tail -f logs/app.log
```

`scripts/make_call.sh` posts to `/call/start` using the current `APP_BASE_URL`. Edit the JSON block to flip `"simulate": true` for local dry runs (no PSTN usage) or set a specific `target_phone_number`.

---

## Calling API

`POST /call/start`

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `target_phone_number` | string or null | `.env` `TARGET_PHONE_NUMBER` | Override the callee per call. Must be E.164 when provided. |
| `system_prompt` | string or null | `DEFAULT_SYSTEM_PROMPT` | Per-call prompt override. Plain text only. |
| `simulate` | boolean | `false` | When `true`, skip ACS entirely and spin up the Voice Live session locally. |

Example simulated call:

```bash
curl -X POST "$APP_BASE_URL/call/start" \
  -H "Content-Type: application/json" \
  -d '{
    "target_phone_number": null,
    "system_prompt": null,
    "simulate": true
  }'
```

When the call is real (not simulated), ACS creates a call, invokes `/call/events`, and opens the `/media/{token}` WebSocket. The FastAPI app then connects to Voice Live and bridges audio in both directions.

---

## Prompts

Two prompt layers steer the conversation:

* **System prompt** – global guardrails for tone, privacy, cadence. Default lives in `.env` but can be overridden per request.
* **CALL_BRIEF** – patient-specific context produced by the notebook or precomputed upstream.

Example system prompt snippet:

```text
BEGIN SYSTEM
ROLE: Realtime calling assistant for {CLINIC_NAME}. Goal: schedule preventive care.
FLOW: greet → confirm identity → check-in → purpose → schedule.
PRIVACY: First name only until identity confirmed. No PHI over voicemail.
STYLE: Warm, brief, plain language. 8–18 words per turn.
SAFETY: No diagnoses or medical advice. Escalate urgent symptom mentions to emergency services.
END SYSTEM
```

The `CALL_BRIEF` retains the same structure as the preview build (see `notebook/` for generators). Injecting both keeps the agent grounded on the correct patient, need, and prior touchpoints.

---

## Script toolbox

| Script | Purpose |
| ------ | ------- |
| `load_env.sh` | Merge `.env` + `.env.local` (optionally more) into the current shell. Falls back to pure Bash if Python is unavailable. |
| `start.sh` | Launch the FastAPI app (Gunicorn on Unix, uvicorn on Windows). |
| `ngrok_auth.sh` | One-time ngrok auth token setup. |
| `ngrok_tunnel.sh` | Launch ngrok on port 8000 and print the public URL. |
| `poll_status.sh` | Repeatedly call `/status` and pretty-print the JSON response. |
| `make_call.sh` | Fire `POST /call/start` with an editable JSON body (includes the `simulate` toggle). |
| `deploy.sh` | Helper for packaging/pushing to Azure (customize before real deployments). |

---

## Observability

* `/status` returns counters such as `inFrames`, `outFrames`, `audio_bytes_in/out`, `last_flush_reason`, and high-level call state.
* Logs (stdout and `logs/app.log`) capture ACS webhook events, Voice Live lifecycle, and input flush diagnostics. Set `LOG_LEVEL=DEBUG` (in `.env` or `.env.local`) to expand detail; add `DEBUG_VOICELIVE_INPUT_FLUSH=true` when you need RMS per flush.

---

## Tuning cheatsheet

| Issue | What to tweak |
| ----- | ------------- |
| Agent replies too slowly after caller stops speaking | Lower `VOICELIVE_INPUT_FLUSH_FRAMES` to `3` or reduce `VOICELIVE_INPUT_FLUSH_INTERVAL_MS` to `40`. |
| Voice Live receives choppy audio | Increase `VOICELIVE_INPUT_FLUSH_FRAMES` or raise `VOICELIVE_INPUT_FLUSH_MAX_INTERVAL_MS` so flushes carry more context. |
| Silence detected prematurely | Set `VOICELIVE_WAIT_FOR_CALLER=false` so the agent greets first (for inbound-type flows) or tweak system prompt guidance. |
| Need to disable outbound synthesis temporarily | Add `MEDIA_ENABLE_VL_OUT=false` to `.env.local`. |
| ACS callbacks 404 | Double-check `APP_BASE_URL` and confirm ngrok is exposing the same URL you configured with ACS. |

All tuning variables and defaults live in [ENV.md](ENV.md).

---

## Troubleshooting

* **Call immediately terminates:** Check `logs/app.log` for missing Voice Live credentials or an `APP_BASE_URL` pointing at `http://`. The service enforces HTTPS for ACS.
* **No audio from the agent:** Confirm `MEDIA_ENABLE_VL_OUT` is `true` and voice frames are leaving the bridge (`outFrames` increasing).
* **Caller audio ignored:** Look for `flush_reason="timer"` spam. Increase `VOICELIVE_INPUT_FLUSH_FRAMES` or inspect RMS telemetry by setting `DEBUG_VOICELIVE_INPUT_FLUSH=true`.
* **ngrok loopback errors:** Make sure `ngrok_tunnel.sh` is running in the same session that sourced the env so `APP_BASE_URL` stays in sync.
* **ACS credential errors:** Remove quotes around `ACS_CONNECTION_STRING`; the loader already handles whitespace.

---

## Notebook (optional)

`notebook/notebook.ipynb` remains for experimentation with synthetic clinical notes. It generates `CALL_BRIEF` payloads via Azure OpenAI **only for offline prep work**, the live call path no longer depends on it.

Environment variables for the notebook are isolated in `.env.notebook` (see [ENV.md](ENV.md)). Running the notebook is optional and not required for testing.

---

## Safety, scope, non-goals

* **Data:** Synthetic only. Production usage demands HIPAA controls, PHI minimization, and key management.
* **Consent:** Always open with identity and purpose, respect opt-outs, and honor do-not-call lists.
* **Guardrails:** The system prompt enforces call flow, tone, and scope; Voice Live responses should remain in scheduling/education territory.
* **Escalation:** No live transfer or clinical triage exists today. Direct callers to a human when medical advice is needed.
* **Integrations:** No writes back to EHR/FHIR/CRM. Scheduling remains mocked to limit scope.

---

## To do & roadmap

Short-term engineering tasks:

* CI: add linting, unit tests, and a simulated `/call/start` smoke test.
* Infrastructure: containerize, publish to Azure App Service/Container Apps, wire secrets via Key Vault.
* Monitoring: publish structured logs + metrics to Azure Monitor / Application Insights.
* Cost guardrails: document ACS and Voice Live quotas, add rate limiting.

Forward-looking roadmap:

* HIPAA readiness (encryption, audit logs, BAA, PHI segmentation).
* Smarter jitter buffer with timestamp drift correction.
* Multi-channel analytics (turn transcripts, sentiment tagging, SMS follow-up experiments).
* Region auto-selection + health checks for lower latency.