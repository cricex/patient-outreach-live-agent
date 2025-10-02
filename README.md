# Preventive Care Gap Closure: Real time Voice Outreach (PoC)
> **Note:** This project originally targeted the Public Preview of Azure Voice Live + Azure OpenAI realtime models. It has now been trimmed to a **GA-only Speech (Voice Live) implementation** (preview plumbing removed) as of 2025/10/01. See commit history for the migration path.

> **Purpose:** Demonstrate an end to end voice pipeline that identifies patients due for preventive screenings from synthetic EHR like data, generates a concise reason for outreach, and calls them to book an appointment using Azure Communication Services, Azure AI Voice Live service, and Azure OpenAI realtime models for low latency, multilingual speech to speech.

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
9. [Prompts](#prompts)
10. [Scripts](#scripts)
11. [Observability](#observability)
12. [Tuning and Known Behaviors](#tuning-and-known-behaviors)
13. [Troubleshooting](#troubleshooting)
14. [Notebook: Preventive Outreach and CALL_BRIEF](#notebook-preventive-outreach-and-call_brief)
15. [Safety, Scope, and Non Goals](#safety-scope-and-non-goals)
16. [To Do](#to-do)
17. [Roadmap](#roadmap)

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
  * is powered by **Azure Communication service** and **Azure AI Voice Live service** with **Azure OpenAI realtime models** for speech to speech

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

## Architecture Overview

```
Simulated EHR -> Gap Detector -> Patient Summary (CALL_BRIEF)
                         |
                      FastAPI App
   ACS Webhooks and Media WS        Azure AI Voice Live WS
                 \                          /
                 Pacer + Jitter Buffer + VAD
                           |
                 Azure OpenAI Realtime Models
                           |
                        Phone Call
```

* Telephony: Azure Communication Services for PSTN, event webhooks, media WebSocket
* Realtime voice: **Azure AI Voice Live service** and **Azure OpenAI realtime models**
* App: FastAPI with a bidirectional audio bridge, adaptive commit, jitter buffer, pacing
* State and metrics: In memory, exposed at `/status`

**Key runtime endpoints**

* `POST /call/start` to create an outbound call
* `POST /call/events` for ACS call lifecycle events
* `WS /media/{token}` for the real time audio bridge
* `GET /status` for live counters and health

---

## Features

* Outbound PSTN calls using ACS
* Bidirectional low latency audio streaming between the phone, **Azure AI Voice Live service**, and **Azure OpenAI realtime models**
* AI powered conversation using Voice Live plus OpenAI realtime, with configurable system prompt and voice
* Parameter driven calls with per request overrides for target number and prompt
* Dynamic audio playback from the AI back to the callee
* Event driven call management via ACS callbacks
* Detailed status monitoring at `/status`
* Adaptive VAD and pacing to buffer, commit, and synthesize with minimal lag
* **Context injection** per call. The `CALL_BRIEF` is injected so the agent speaks to the right patient, procedure, and timing
* **Safety guardrails** via system prompt and policies. Identity disclosure, purpose, opt out, respectful tone, non clinical scope, and language control

---

## Prerequisites

* Python 3.10 or higher
* Azure subscription
* Azure Communication Services resource with an outbound phone number
* Azure Speech resource with Voice Live GA enabled (SPEECH_KEY, SPEECH_REGION)
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

This project uses three separate environment files to manage configuration for different environments. This separation makes the deployment process more robust and prevents local development settings from accidentally leaking into production.

1.  **`.env`**: Contains settings **exclusively for deployment to Azure**. This file should contain all the necessary secrets and configuration that the live application will use. It is read by the `scripts/deploy.sh` script.
2.  **`.env.local`**: For **local development overrides**. Variables in this file will take precedence over those in `.env` when running the application locally. This is the place for your `ngrok` URL, local logging settings, etc.
3.  **`.env.notebook`**: Contains settings **specific to the Jupyter notebook** (`notebook/notebook.ipynb`), such as the Azure OpenAI credentials for generating `CALL_BRIEF` summaries.

**Setup:**

1.  Copy `.env.sample` to a new file named `.env` and fill in the values for your Azure deployment.
2.  Create a `.env.local` file for your local overrides.
3.  Create a `.env.notebook` file for your notebook credentials.

> **Security Note:** The `.gitignore` file is configured to ignore `.env`, `.env.local`, and `.env.notebook`, so your secrets will not be committed to source control.

### Key Variables

| Variable                  | Description                                                                   | Found In                               |
| ------------------------- | ----------------------------------------------------------------------------- | -------------------------------------- |
| `APP_BASE_URL`            | Public base URL of your app (e.g., ngrok URL for local, Azure URL for prod).  | `.env.local` (local), set by script (prod) |
| `ACS_CONNECTION_STRING`   | Your full Azure Communication Services connection string.                     | `.env`                                 |
| `ACS_OUTBOUND_CALLER_ID`  | The E.164 phone number to use as the caller ID.                               | `.env`                                 |
| `TARGET_PHONE_NUMBER`     | The default phone number to call.                                             | `.env`                                 |
| `SPEECH_KEY`              | Azure Speech subscription key (Voice Live GA).                                | `.env`                                 |
| `SPEECH_REGION`           | Azure Speech region (e.g. `eastus`).                                          | `.env`                                 |
| `DEFAULT_VOICE`           | The default TTS voice for the agent.                                          | `.env`                                 |
| `LOG_LEVEL`               | Logging level for local development (`DEBUG`, `INFO`, etc.).                  | `.env.local`                           |
| `AZURE_OPENAI_ENDPOINT`   | Endpoint for the Azure OpenAI resource used by the notebook.                  | `.env.notebook`                        |
| `AZURE_OPENAI_KEY`        | API key for the Azure OpenAI resource used by the notebook.                   | `.env.notebook`                        |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | The chat model deployment used by the notebook.                          | `.env.notebook`                        |

For a complete list of all advanced tuning variables, see `ENV.md`.

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

The `system_prompt` and the injected `CALL_BRIEF` guide the agent so the conversation remains unscripted, context aware, and within guardrails.

---

## Prompts

This app uses two prompt inputs:

- **SYSTEM:** Defines the assistant role, tone, privacy, and call flow.
- **CALL_BRIEF:** Supplies patient specific context for the call.

Use the generic templates below in local testing or CI demos. Keep them plain text.

### SYSTEM prompt example & template
```bash
BEGIN SYSTEM
ROLE: Realtime calling assistant for {CLINIC_NAME}. Goal: schedule preventive care.
LANGUAGE: {LANGUAGE}. Plain text only. No emojis or SSML.
STYLE: Warm, brief, natural. 8 to 18 words per turn. Contractions OK.
PRIVACY: Use first name only. Share details only after identity confirmed. No numbers or links.

FLOW: greet → confirm identity → quick check-in → purpose → answer relevant questions → schedule.
ONE QUESTION RULE: Ask one question at a time. Confirm once for need, date, time, location.

DATE SPEECH:

Do not read raw digits. Speak dates as “Month Year” or “Month day, Year” if asked.

2024-08 → “by August 2024”; 2013-10-08 → “back in October 2013”; 1 to 3 months → “in the next one to three months.”

WHY ANSWERS (after ID confirmed):

Cite BRIEF.WHY in one friendly sentence.

Optionally add one dated item from BRIEF.HISTORY using DATE SPEECH.

Pattern: “Because {WHY}. Also, you were advised in {Month Year}.”

TOPIC CADENCE AND STATE:

Maintain per-topic flags: {check_back_used: false, offer_used: false}.

CHECK BACK GUARD: Use a check-back only when your explanation is longer than one sentence, the patient sounded unsure, or they asked why or what or how. Never in two consecutive turns. Max one per topic unless the patient asks to clarify.

OFFER GUARD: Do not offer to book in two consecutive turns. Offer at most once per topic unless the patient shows intent.

INTENT GATE: Move to preferences only after an explicit yes or clear scheduling intent.

DEFERRAL: If “not now,” acknowledge and offer a later reminder once. Do not re-offer unless the patient re-initiates.

ON OR OFF TOPIC:

Relevant “what is” questions: give one-sentence overview, then continue to scheduling.

Off-topic: acknowledge and redirect to scheduling.

SAFETY:

No diagnoses or personalized medical advice. If urgent symptoms, advise emergency services and end.

If caller is not the patient, request permission before discussing details.

Respect opt out immediately.

MICRO TEMPLATES (rotate; do not repeat within two turns):
CHECK BACK: “Does that help?” | “Is that clear?” | “Want a quick recap?”
ACKS: “Great to hear.” | “Got it.” | “Sorry to hear that.”
OFFERS: “Want to set that up now?” | “Shall we find a time?”
INTENT FOLLOW UP: “Happy to set it up. What days work best?”
DEFERRAL: “No problem. Want a reminder in a few months?”
REDIRECT: “I may not have that, but I can help schedule your care. Would this week work?”

END SYSTEM
```

### CALL_BRIEF template and example
```shell
BEGIN CALL_BRIEF
PATIENT_FIRST_NAME: John
TOP_NEED: colonoscopy
PRIORITY: routine
TIMING: this month
WHY: Due for preventive screening based on guidelines and prior advice.
HISTORY: Referred in February 2021; reminded in March 2024; no completed colonoscopy on record.
DO_NOT_SAY: IDs, age numbers, detailed history unless asked.
OPENERS: Hi John, I am calling from {CLINIC_NAME}. Is this John? | How are you today? | I am calling because you may be due for a colonoscopy. Does that sound right?
OVERVIEW_COLONOSCOPY: It checks the colon for polyps and cancer and helps prevent cancer.
WHY_EXAMPLE: Because screening is due based on guidelines and prior advice. Also, you were advised in March 2024.
SCHED_STARTERS: Can we look at times this week? | Do mornings or afternoons work better?
END CALL_BRIEF
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

| Use case                          | Notebook | App                       |
| --------------------------------- | -------- | ------------------------- |
| Prompt and content iteration      | Yes      | No                        |
| Unscripted real time conversation | No       | Yes                       |
| Small batch generation            | Yes      | Limited and not optimized |
| End to end voice validation       | No       | Yes                       |

**Limitations**
Single threaded, minimal error handling, not schema rigorous, not a medical device, no HIPAA controls, outbound demo is one way only.

---

## Safety, Scope, and Non Goals

* **Data**
  Synthetic only in this repo. Production requires HIPAA controls, a BAA, audit, and data minimization.

* **Consent and disclosures**
  Open with identity, purpose, and opt out. Respect do not call lists.

* **Guardrails**
  Conversations are unscripted but constrained by system instructions and the injected `CALL_BRIEF`. The agent

  * stays within reminder, education, and scheduling scope
  * avoids clinical diagnosis, treatment, or individualized medical advice
  * discloses identity and purpose, honors opt out, and maintains a respectful tone
  * uses the selected language consistently
  * minimizes sensitive data in prompts and logs

* **Escalation**
  This PoC does not support live transfer or triage to a human. If a caller requests clinical guidance or complex help, instruct them to contact the clinic directly.

* **Write back and integrations**
  This PoC does not write back to an EHR, FHIR store, scheduler, or CRM. All scheduling is mocked.

* **Fairness**
  Use consistent scripts across languages in plain language.

**PoC in scope**
Synthetic gap detection, patient summary, multilingual live calling, mocked scheduling, basic metrics

**Out of scope**
EHR write back, clinical triage or escalation, payer rules, PHI storage, security hardening

---

## To Do

Near term, actionable engineering tasks.

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
* Document cost guardrails and quotas for ACS and Azure OpenAI usage
* Validate security headers, CORS, and rate limits in the FastAPI app

---

## Roadmap

Forward looking product and compliance work.

* HIPAA readiness path

  * Define architectural controls such as encryption in transit and at rest, key management in Key Vault, audit logging, access controls, PHI segmentation
  * Replace synthetic data with secure integration patterns and a no PHI local mode for testing
  * Add FHIR scheduling integration and secure storage
  * Complete BAA process and formal risk assessment
* Smarter jitter buffer with time stamped frames and drift correction
* A or B scripts and SMS follow ups
* Automated region pinning and health checks
* Light schema validation and a small worker pool for notebook batching