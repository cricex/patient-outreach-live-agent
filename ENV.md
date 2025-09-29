# Environment Variables

This file documents all the environment variables used by the application. The configuration is split across three files:

-   **`.env`**: Contains variables for deployment to Azure.
-   **`.env.local`**: Contains variables for local development, which override the defaults.
-   **`.env.notebook`**: Contains variables used exclusively by the Jupyter notebook.

---

## 🚀 Deployment & Core Application (`.env`)

These variables are essential for the deployed application. They should be placed in the main `.env` file.

| Variable                | Description                                                                                             | Required |
| ----------------------- | ------------------------------------------------------------------------------------------------------- | :------: |
| `ACS_CONNECTION_STRING` | The full connection string for your ACS resource.                                                       |   Yes    |
| `ACS_ENDPOINT`          | The endpoint URL for your ACS resource. (Usually inferred from the connection string).                  |    No    |
| `ACS_OUTBOUND_CALLER_ID`| The E.164 formatted phone number to use as the caller ID for outbound calls.                              |   Yes    |
| `TARGET_PHONE_NUMBER`   | The default recipient's E.164 phone number for outbound calls.                                            |    No    |
| `AI_FOUNDRY_ENDPOINT`   | The WebSocket endpoint for your Azure OpenAI Voice Live deployment.                                     |   Yes    |
| `AI_FOUNDRY_API_KEY`    | The API key for your Azure OpenAI resource.                                                             |   Yes    |
| `VOICE_LIVE_MODEL`      | The specific Voice Live model to use (e.g., `gpt-4o-realtime-preview`).                                   |   Yes    |
| `DEFAULT_VOICE`         | The default TTS voice to use for the agent's responses (e.g., `en-US-AvaNeural`).                         |   Yes    |
| `DEFAULT_SYSTEM_PROMPT` | The default system prompt for the AI agent if none is provided in the call request.                     |   Yes    |
| `ENABLE_VOICE_LIVE`     | A feature flag to enable or disable the Voice Live integration.                                         |    No    |
| `CALL_TIMEOUT_SEC`      | The absolute maximum duration of a call in seconds before it is automatically terminated.               |    No    |
| `CALL_IDLE_TIMEOUT_SEC` | The number of seconds of inactivity (no audio or events) before a call is automatically terminated.     |    No    |

---

## � Local Development (`.env.local`)

These variables are used for local development and will override settings in `.env`.

| Variable                | Description                                                                                             | Required | Default Value |
| ----------------------- | ------------------------------------------------------------------------------------------------------- | :------: | ------------- |
| `APP_BASE_URL`          | The public base URL of your local application, used for ACS webhooks (e.g., your `ngrok` URL).            |   Yes    | (none)        |
| `NGROK_AUTH_TOKEN`      | Your ngrok authentication token.                                                                        |    No    | (none)        |
| `LOG_LEVEL`             | The logging level for the application (`DEBUG`, `INFO`, `WARNING`, etc.).                               |    No    | `INFO`        |
| `LOG_DIR`               | The directory to store log files in.                                                                    |    No    | `logs`        |
| `LOG_FILE_MAX_KB`       | The maximum size of a log file in kilobytes before it is rotated.                                       |    No    | `200`         |
| `LOG_FILE_BACKUP_COUNT` | The number of old log files to keep.                                                                    |    No    | `10`          |
| `LOG_FILE_ENABLE`       | If `true`, forces file logging even if `LOG_LEVEL` is not `DEBUG`.                                      |    No    | `false`       |
| `MEDIA_DUMP_WAV`        | If `true`, saves the incoming call audio to a WAV file for debugging.                                   |    No    | `false`       |

---

## 📓 Jupyter Notebook (`.env.notebook`)

These variables are used exclusively by the `notebook/notebook.ipynb`.

| Variable                       | Description                                                                                             | Required |
| ------------------------------ | ------------------------------------------------------------------------------------------------------- | :------: |
| `AZURE_OPENAI_ENDPOINT`        | The endpoint for the Azure OpenAI resource used for generating `CALL_BRIEF` summaries.                  |   Yes    |
| `AZURE_OPENAI_KEY`             | The API key for the Azure OpenAI resource.                                                              |   Yes    |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | The name of the chat model deployment (e.g., `gpt-4`).                                                  |   Yes    |
| `AZURE_OPENAI_API_VERSION`     | The API version for the Azure OpenAI service.                                                           |   Yes    |
| `NOTES_PATH`                   | The local path to the directory containing the synthetic clinical notes.                                |   Yes    |

---

## ⚙️ Advanced Media & Latency Tuning

These variables can be placed in either `.env` (for production) or `.env.local` (for local testing) to fine-tune performance.

| Variable                         | Description                                                                                             | Default Value |
| -------------------------------- | ------------------------------------------------------------------------------------------------------- | ------------- |
| `MEDIA_BIDIRECTIONAL`            | Use bidirectional media streaming with ACS.                                                             | `true`        |
| `MEDIA_AUDIO_CHANNEL_TYPE`       | The audio channel type from ACS. Can be `mixed` or `unmixed`.                                           | `mixed`       |
| `VL_INPUT_MIN_MS`                | Minimum milliseconds of audio to buffer before committing to the model.                                 | `160`         |
| `VL_INPUT_SAFETY_MS`             | Additional safety margin (ms) added to the adaptive minimum commit threshold.                           | `40`          |
| `VL_MAX_BUFFER_MS`               | Safety cap in milliseconds for the audio buffer before a forced commit.                                 | `2000`        |
| `VL_SILENCE_COMMIT_MS`           | Silence gap in milliseconds that triggers an end-of-phrase commit.                                      | `140`         |
| `VL_DYNAMIC_RMS_OFFSET`          | Base additive RMS offset above the noise floor to detect speech.                                        | `300`         |
| `VL_MIN_SPEECH_FRAMES`           | Minimum number of consecutive speech frames (~20ms each) required to trigger a commit.                  | `5`           |
| `VL_BOOTSTRAP_DURATION_MS`       | Window (ms) at the start of a call that uses more sensitive VAD settings to detect first speech.        | `2000`        |
| `VL_BOOTSTRAP_RMS_OFFSET`        | A lower, more sensitive RMS offset used during the bootstrap window.                                    | `80`          |
| `VL_BOOTSTRAP_MIN_SPEECH_FRAMES` | Minimum speech frames required during the bootstrap window.                                             | `3`           |
| `VL_OFFSET_DECAY_STEP`           | Amount to reduce the RMS offset by during prolonged silence while hunting for speech.                   | `10`          |
| `VL_OFFSET_DECAY_INTERVAL_MS`    | Interval (ms) for applying the RMS offset decay.                                                        | `200`         |
| `VL_OFFSET_DECAY_MIN`            | The floor for the decayed RMS offset.                                                                   | `40`          |
| `VL_BARGE_IN_ENABLED`            | Feature flag to enable or disable barge-in detection.                                                   | `true`        |
| `VL_BARGE_IN_OFFSET`             | A sensitive RMS offset used for detecting barge-in while the agent is speaking.                         | `40`          |
| `VL_BARGE_IN_CONSECUTIVE_FRAMES` | Number of consecutive frames above the barge-in threshold required to trigger an interruption.          | `3`           |
| `VL_LOG_FIRST_COMMIT`            | If `true`, emits a structured log with detailed timing information for the first audio commit.          | `true`        |
