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
| `SPEECH_KEY`            | Azure Speech (Voice Live GA) subscription key.                                                         |   Yes    |
| `SPEECH_REGION`         | Azure Speech region (e.g., `eastus`).                                                                  |   Yes    |
| `DEFAULT_VOICE`         | The default TTS voice to use for the agent's responses (e.g., `en-US-AvaNeural`).                         |   Yes    |
| `DEFAULT_SYSTEM_PROMPT` | The default system prompt for the AI agent if none is provided in the call request.                     |   Yes    |
| `VOICELIVE_LANGUAGE_HINT` | Optional language directive appended to the Voice Live system prompt (e.g., `English`, `en-US`).        |    No    |
| `VOICELIVE_WAIT_FOR_CALLER` | If `true`, adds guidance so the agent waits silently for the callee to greet first (recommended for outbound). |    No    |
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

## ⚙️ Advanced Media & Latency (GA Simplified)

The GA Voice Live integration no longer requires manual VAD / commit tuning. All legacy `VL_*` variables from the preview implementation are **deprecated** and ignored. You can remove them from your environment files.

| Variable                 | Description                                                       | Default Value |
| ------------------------ | ----------------------------------------------------------------- | ------------- |
| `MEDIA_BIDIRECTIONAL`    | Use bidirectional media streaming with ACS.                      | `true`        |
| `MEDIA_AUDIO_CHANNEL_TYPE` | The audio channel type from ACS (`mixed` or `unmixed`).          | `mixed`       |
| `SPEECH_KEY`             | Azure Speech (GA Voice Live) subscription key.                   | (none)        |
| `SPEECH_REGION`          | Azure Speech region (e.g., `eastus`).                            | (none)        |
