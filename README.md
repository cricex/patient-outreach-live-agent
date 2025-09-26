# Preventive Care Gap Closure — Real time Voice Outreach (PoC)

> **Purpose:** Demonstrate an end to end voice pipeline that identifies patients due for preventive screenings from synthetic EHR like data, generates a concise reason for outreach, and calls them to book an appointment using Azure Communication Services and Azure OpenAI Voice Live for low latency, multilingual speech to speech.

> **HIPAA disclaimer:** This repository is exploratory. It is not HIPAA compliant. Do not use with real PHI. The long term intent is to develop a compliant variant with proper safeguards. See To Do and Roadmap.

> **General disclaimer:** This code is exploratory. It is not production ready. Review, validate, and re implement with appropriate safeguards before any clinical or operational deployment.

---

## Index

1. [Scenario: What It Does and Why It Matters](#scenario-what-it-does-and-why-it-matters)
2. [Architecture Overview](#architecture-overview)
3. [Features](#features)
4. [Prerequisites](#prerequisites)
5. [Installation](#installation)
6. [.env Configuration](#env-configuration)
7. [Quick Start](#quick-start)
8. [API Usage](#api-usage)
9. [Scripts](#scripts)
10. [Observability](#observability)
11. [Tuning and Known Behaviors](#tuning-and-known-behaviors)
12. [Troubleshooting](#troubleshooting)
13. [Notebook: Preventive Outreach and CALL_BRIEF](#notebook-preventive-outreach-and-call_brief)
14. [Safety, Scope, and Non Goals](#safety-scope-and-non-goals)
15. [To Do](#to-do)
16. [Roadmap](#roadmap)

---

## Scenario: What It Does and Why It Matters

### What it does

* Detects preventive care gaps from synthetic EHR like JSON such as mammogram or colonoscopy due
* Summarizes patient context in plain language as a `CALL_BRIEF`
* Calls the patient and runs a real time, multilingual conversation that

  * explains the screening
  * answers common non clinical questions
  * offers appointment times using a mocked scheduler or routes to a human
* Logs outcomes such as booked, declined, callback to a PoC datastore and exposes basic status metrics

### Why it matters

* Clinical quality: More on time screenings improve early detection
* Operational impact: Lower cost outreach can recover reimbursable services
* Revenue impact: Increases completed preventive visits, captures quality incentives, supports value based contracts, and drives appropriate downstream services
* Equity: Native language conversations reduce access barriers

**Example dialog**

* Agent: “Hi [Name], I am calling from [Clinic]. You are due for a mammogram. Your last one was June 2023. I can help schedule. Do mornings or afternoons work better”
* Patient: “Afternoons.”
* Agent: “I have Tuesday at 3:20 pm or Thursday at 1:40 pm at Main Street. Which works”

---

## Architecture Overview

```
Simulated EHR -> Gap Detector -> Patient Summary (CALL_BRIEF)
                         |
                      FastAPI App
   ACS Webhooks and Media WS        Azure OpenAI Voice Live WS
                 \                          /
                 Pacer + Jitter Buffer + VAD
                           |
                        Phone Call
```

* Telephony: Azure Communication Services for PSTN, event webhooks, media WebSocket
* Realtime voice: Azure OpenAI Voice Live for ASR, TTS, and turn taking
* App: FastAPI with a bidirectional audio bridge, adaptive commit, jitter buffer, pacing
* State and metrics: In memory, exposed at `/status`

**Key runtime endpoints**

* `POST /call/start` to create an outbound call
* `POST /call/events` for ACS call lifecycle events
* `WS /media/{token}` for the real time audio bridge
* `GET /status` for live counters and health

---

## Features

* Outbound PSTN calls using ACS and a purchased number
* Bidirectional low latency audio streaming between phone and Voice Live
* AI powered conversation with configurable system prompt and voice
* Parameter driven calls with per request overrides of target number and prompt
* Dynamic audio playback from the AI back to the callee
* Event driven call management via ACS callbacks
* Detailed status monitoring at `/status`
* Adaptive VAD and pacing to buffer, commit, and synthesize with minimal lag

---

## Prerequisites

* Python 3.10 or higher
* Azure subscription
* Azure Communication Services resource with an outbound phone number
* Azure OpenAI resource with a Voice Live deployment and API key
* `ngrok` for a public HTTPS tunnel during local development

---

## Installation

```bash
git clone <repository-url>
cd <repository-directory>

python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
```

---

## .env Configuration

Create a `.env` file in the repo root.

| Variable                                      | Description                                   | Example                                                 |
| --------------------------------------------- | --------------------------------------------- | ------------------------------------------------------- |
| `APP_BASE_URL`                                | Public base URL of your app such as ngrok URL | `https://<subdomain>.ngrok-free.app`                    |
| `ACS_CONNECTION_STRING`                       | ACS resource connection string                | `endpoint=...;accesskey=...`                            |
| `ACS_FROM_NUMBER` or `ACS_OUTBOUND_CALLER_ID` | E.164 caller ID purchased in ACS              | `+18005551234`                                          |
| `ACS_TO_NUMBER` or `TARGET_PHONE_NUMBER`      | Default callee phone number                   | `+18005555678`                                          |
| `VL_WS_URL` or `AI_FOUNDRY_ENDPOINT`          | Voice Live WebSocket URL                      | `wss://<resource>.openai.azure.com/openai/realtime?...` |
| `VL_API_KEY` or `AI_FOUNDRY_API_KEY`          | Azure OpenAI API key                          | `***`                                                   |
| `VOICE_LIVE_MODEL`                            | Voice Live model deployment name              | `gpt-4o-realtime-preview`                               |
| `VL_VOICE` or `DEFAULT_VOICE`                 | Default TTS voice                             | `verse` or `en-US-AvaNeural`                            |
| `MEDIA_CHANNEL`                               | `MIXED` or `UNMIXED`                          | `MIXED`                                                 |
| `MEDIA_BIDIRECTIONAL`                         | Enable both directions                        | `true`                                                  |
| `MEDIA_OUT_FORMAT`                            | Single outbound format for stability          | `json_simple`                                           |
| `MEDIA_VL_INPUT_MIN_MS`                       | Minimum buffered milliseconds before commit   | `180`                                                   |
| `MEDIA_MIN_MARGIN_MS`                         | Safety margin above model minimum             | `40`                                                    |
| `REGION_HINT`                                 | Co locate app and model to reduce jitter      | `virginia`                                              |

For advanced options see `ENV.md` if present.

---

## Quick Start

### One liners

```bash
# Expose port 8000 publicly
ngrok http 8000

# Start the app
uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info

# Place a test call
curl -s -X POST "$APP_BASE_URL/call/start" -H 'content-type: application/json' -d '{}' | jq

# Check live status
curl -s "$APP_BASE_URL/status" | jq
```

### Scripted flow

```bash
# Load environment
source scripts/load_env.sh

# Start ngrok
./scripts/ngrok_tunnel.sh
# First time only
# ./scripts/ngrok_auth.sh

# Start server
./scripts/start.sh

# Poll status
./scripts/poll_status.sh

# Initiate a call
./scripts/start_call.sh
```

---

## API Usage

`POST /call/start` accepts optional overrides

* `target_phone_number` string in E.164 format. Defaults to `.env` target if null or omitted
* `system_prompt` string. Defaults to `.env` prompt if null or omitted

**Examples**

```bash
# Default call using .env
curl -X POST "$APP_BASE_URL/call/start" \
  -H "Content-Type: application/json" \
  -d '{"target_phone_number": null, "system_prompt": null}'

# Override phone number
curl -X POST "$APP_BASE_URL/call/start" \
  -H "Content-Type: application/json" \
  -d '{"target_phone_number": "+15551234567", "system_prompt": null}'

# Override system prompt
curl -X POST "$APP_BASE_URL/call/start" \
  -H "Content-Type: application/json" \
  -d '{"target_phone_number": null, "system_prompt": "You are a friendly scheduler. Keep answers short."}'
```

---

## Scripts

| Script            | Description                                                                   |
| ----------------- | ----------------------------------------------------------------------------- |
| `load_env.sh`     | Loads `.env` into the current shell without eval                              |
| `start.sh`        | Starts the app server. Uses gunicorn on Linux or macOS and uvicorn on Windows |
| `ngrok_tunnel.sh` | Opens an ngrok tunnel for port 8000                                           |
| `ngrok_auth.sh`   | Sets the ngrok auth token. Run once                                           |
| `poll_status.sh`  | Polls `/status` and pretty prints JSON with jq                                |
| `start_call.sh`   | Triggers `POST /call/start`. You can edit the JSON body here                  |

---

## Observability

**`GET /status`** exposes live counters and flags such as

* `inFrames`, `outFrames`, `audio_bytes_in`, `audio_bytes_out`
* `last_commit_frames`, `last_commit_ms`, `commit_errors_total`
* `audio_rms_avg`, `audio_frames_non_silent`
* `vl_in_started_at`, `schema`, `upstreamActive`

Logs at INFO or DEBUG trace

* ACS media WebSocket handshake and ACK
* Voice Live session events
* Pacer ticks, queue backpressure, send errors

---

## Tuning and Known Behaviors

* **Commit underflows**
  The model needs about 100 ms or more per commit. The app adapts dynamically using `MEDIA_VL_INPUT_MIN_MS` and `MEDIA_MIN_MARGIN_MS`. If commits are too small, raise `MEDIA_VL_INPUT_MIN_MS` to 200 to 220.

* **Jittery or jumpy downlink**
  Often queue overflow or pacing drift. Mitigations

  * Use a single outbound format such as `json_simple` to prevent duplicates
  * Use a pacer that sends one 640 byte frame about every 20 ms with a jitter buffer
  * Drop oldest only when the queue saturates

* **Slow pitch audio**
  Usually duplicate or mismatched formats. Standardize frame size and use a single outbound format.

* **Region latency**
  Co locate app and model such as both in Virginia. Cross country round trip time can starve the pacer.

---

## Troubleshooting

* **Calls drop after about 80 seconds**
  Historically an idle timeout. Verify that state updates occur on Voice Live events and that `app_state.update_last_event()` is invoked where applicable.

* **ACS MediaStreamingFailed 1006 transport not operational**
  Send an ACK immediately after accepting the media WebSocket. Ensure a public HTTPS endpoint through ngrok and align resource regions.

* **No AI audio heard**
  Confirm `outFrames` increases, `MEDIA_OUT_FORMAT=json_simple` is set, and pacer logs show frames leaving the queue.

* **Model is not detecting your speech**
  Confirm `audio_frames_non_silent` is greater than 0 and `last_commit_ms` is at least 120. Increase `MEDIA_VL_INPUT_MIN_MS` if needed.

* **APP_BASE_URL not set**
  Source `scripts/load_env.sh` in the same terminal running your scripts.

* **404 from ACS**
  Ensure `APP_BASE_URL` exactly matches your active ngrok URL.

* **ngrok fails to start**
  Verify `NGROK_AUTH_TOKEN` and that you ran `./scripts/ngrok_auth.sh` once.

---

## Notebook: Preventive Outreach and `CALL_BRIEF`

The repo includes an exploratory notebook at `notebook/notebook.ipynb`. It generates structured preventive care summaries called `CALL_BRIEF` from synthetic clinical note JSON and can optionally produce a short one way outbound message.

**What it does**

1. Loads a folder of JSON clinical note objects in `notebook/clinical_notes`
2. Calls an Azure OpenAI chat deployment with a strict system prompt that returns

   ```json
   {
     "patient_id": "...",
     "appointment_needed": true,
     "call_brief": "BEGIN CALL_BRIEF ... END CALL_BRIEF"
   }
   ```
3. Builds a small DataFrame across patients
4. Optionally turns a selected `CALL_BRIEF` into a 15 to 35 word outbound message
5. Optional demo places a non interactive ACS call that only plays the generated text

**Synthetic OMOP like notes**
Inputs are synthetic and loosely OMOP like. They are flattened and simplified for LLM prompt experimentation. No real PHI is present.

**Notebook environment variables**

| Variable                                             | Purpose                                     |
| ---------------------------------------------------- | ------------------------------------------- |
| `NOTES_PATH`                                         | Directory containing synthetic patient JSON |
| `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_KEY`       | Azure OpenAI resource and key               |
| `AZURE_OPENAI_DEPLOYMENT_NAME`                       | Chat model deployment                       |
| `AZURE_OPENAI_API_VERSION`                           | API version string                          |
| `TTS_VOICE`                                          | Voice for the one way call demo             |
| `TARGET_PHONE_NUMBER`                                | Callee for the demo                         |
| `ACS_CONNECTION_STRING` and `ACS_OUTBOUND_CALLER_ID` | Required for the call demo                  |

**When to use Notebook vs App**

| Use case                        | Notebook | App                       |
| ------------------------------- | -------- | ------------------------- |
| Prompt and content iteration    | Yes      | No                        |
| Streaming, turn taking, latency | No       | Yes                       |
| Small batch generation          | Yes      | Limited and not optimized |
| End to end voice validation     | No       | Yes                       |

**Limitations**
Single threaded, minimal error handling, not schema rigorous, not a medical device, no HIPAA controls, outbound demo is one way only.

---

## Safety, Scope, and Non Goals

* Data
  Synthetic only in this repo. Production requires HIPAA controls, a BAA, audit, and data minimization.

* Consent and disclosures
  Open with identity, purpose, and opt out. Respect do not call lists.

* Escalation
  Conversations are non clinical. Clinical signals route to a human.

* Fairness
  Use consistent scripts across languages in plain language.

**PoC in scope**
Synthetic gap detection, patient summary, multilingual live calling, mocked schedule, basic metrics

**Out of scope**
EMR write back, clinical triage, payer rules, PHI storage, security hardening

---

## To Do

* Deploy to Azure with repeatable infrastructure

  * Containerize the FastAPI app
  * Host on Azure App Service or Azure Container Apps
  * Use Azure Key Vault for secrets and rotate keys on a schedule
  * Configure Azure Monitor and Application Insights for logs and metrics
  * Pin ACS and Azure OpenAI resources to regions that minimize round trip time
  * Set up a custom domain and TLS
  * Provide a basic Bicep or Terraform template in `infra`
* Add automated smoke tests for `/call/start`, `/media`, and `/status`
* Add CI checks such as lint, type check, unit tests, and container build
* Document cost guardrails and quotas for ACS and OpenAI usage
* Prepare a HIPAA readiness checklist in `docs` that maps controls to Azure services
* Validate security headers, CORS, and rate limits in the FastAPI app

---

## Roadmap

* HIPAA readiness path

  * Define architectural controls such as encryption in transit and at rest, key management in Key Vault, audit logging, access controls, PHI segmentation
  * Replace synthetic data with secure integration patterns and a no PHI local mode for testing
  * Add FHIR scheduling integration and secure storage
  * Complete BAA process and formal risk assessment
* Smarter jitter buffer with time stamped frames and drift correction
* A or B scripts and SMS follow ups
* Automated region pinning and health checks
* Light schema validation and a small worker pool for notebook batching