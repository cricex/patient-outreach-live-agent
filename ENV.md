# Environment Variables

This file documents all the environment variables used by the application. Create a `.env` file in the root of the project to set these values.

##  utama Core Application

These variables are essential for the basic operation of the service.

| Variable                  | Description                                                                                             | Required | Default Value                                           |
| ------------------------- | ------------------------------------------------------------------------------------------------------- | :------: | ------------------------------------------------------- |
| `APP_BASE_URL`            | The public base URL of your application, used for ACS webhooks (e.g., your `ngrok` URL).                |   Yes    | `http://localhost:8000`                                 |
| `WEBSITES_PORT`           | The local port on which the web server will run.                                                        |    No    | `8000`                                                  |
| `DEFAULT_SYSTEM_PROMPT`   | The default system prompt for the AI agent if none is provided in the call request.                     |   Yes    | `You are a helpful English voice agent...`              |
| `LOG_LEVEL`               | The logging level for the application.                                                                  |    No    | `INFO`                                                  |

## 📞 Azure Communication Services (ACS)

Variables required for placing outbound calls via ACS.

| Variable                   | Description                                                                                             | Required | Default Value |
| -------------------------- | ------------------------------------------------------------------------------------------------------- | :------: | ------------- |
| `ACS_CONNECTION_STRING`    | The full connection string for your ACS resource.                                                       |   Yes    | (none)        |
| `ACS_ENDPOINT`             | The endpoint URL for your ACS resource. (Usually inferred from the connection string).                  |    No    | (none)        |
| `ACS_OUTBOUND_CALLER_ID`   | The E.164 formatted phone number to use as the caller ID for outbound calls.                              |   Yes    | (none)        |
| `TARGET_PHONE_NUMBER`      | The default recipient's E.164 phone number for outbound calls initiated via `start_call.sh`.      |    No    | (none)        |

## 🧠 Azure AI Voice Live

Variables for connecting to the Azure AI Voice Live service. These are required if `ENABLE_VOICE_LIVE` is `true`.

| Variable                | Description                                                                                             | Required | Default Value |
| ----------------------- | ------------------------------------------------------------------------------------------------------- | :------: | ------------- |
| `ENABLE_VOICE_LIVE`     | A feature flag to enable or disable the Voice Live integration.                                         |    No    | `true`        |
| `AI_FOUNDRY_ENDPOINT`   | The WebSocket endpoint for your Azure OpenAI Voice Live deployment.                                     |   Yes    | (none)        |
| `AI_FOUNDRY_API_KEY`    | The API key for your Azure OpenAI resource.                                                             |   Yes    | (none)        |
| `VOICE_LIVE_MODEL`      | The specific Voice Live model to use (e.g., `gpt-4o-realtime-preview`).                                   |   Yes    | (none)        |
| `DEFAULT_VOICE`         | The default TTS voice to use for the agent's responses (e.g., `en-US-AvaNeural`).                         |   Yes    | (none)        |

## ⏱️ Call Timeouts

Variables to control call duration and prevent orphaned calls.

| Variable                  | Description                                                                                             | Required | Default Value |
| ------------------------- | ------------------------------------------------------------------------------------------------------- | :------: | ------------- |
| `CALL_TIMEOUT_SEC`        | The absolute maximum duration of a call in seconds before it is automatically terminated.               |    No    | `90`          |
| `CALL_IDLE_TIMEOUT_SEC`   | The number of seconds of inactivity (no audio or events) before a call is automatically terminated.     |    No    | `90`          |

## 🔊 VAD & Latency Control (Advanced)

Advanced settings for tuning the Voice Activity Detection (VAD) and latency. Modify these only if you need to fine-tune the agent's responsiveness.

| Variable                         | Description                                                                                             | Required | Default Value |
| -------------------------------- | ------------------------------------------------------------------------------------------------------- | :------: | ------------- |
| `VL_INPUT_MIN_MS`                | Minimum milliseconds of audio to buffer before committing to the model.                                 |    No    | `160`         |
| `VL_INPUT_SAFETY_MS`             | Additional safety margin (ms) added to the adaptive minimum commit threshold.                           |    No    | `40`          |
| `VL_MAX_BUFFER_MS`               | Safety cap in milliseconds for the audio buffer before a forced commit.                                 |    No    | `2000`        |
| `VL_SILENCE_COMMIT_MS`           | Silence gap in milliseconds that triggers an end-of-phrase commit.                                      |    No    | `140`         |
| `VL_DYNAMIC_RMS_OFFSET`          | Base additive RMS offset above the noise floor to detect speech.                                        |    No    | `300`         |
| `VL_MIN_SPEECH_FRAMES`           | Minimum number of consecutive speech frames (~20ms each) required to trigger a commit.                  |    No    | `5`           |
| `VL_BOOTSTRAP_DURATION_MS`       | Window (ms) at the start of a call that uses more sensitive VAD settings to detect first speech.        |    No    | `2000`        |
| `VL_BOOTSTRAP_RMS_OFFSET`        | A lower, more sensitive RMS offset used during the bootstrap window.                                    |    No    | `80`          |
| `VL_BOOTSTRAP_MIN_SPEECH_FRAMES` | Minimum speech frames required during the bootstrap window.                                             |    No    | `3`           |
| `VL_OFFSET_DECAY_STEP`           | Amount to reduce the RMS offset by during prolonged silence while hunting for speech.                   |    No    | `10`          |
| `VL_OFFSET_DECAY_INTERVAL_MS`    | Interval (ms) for applying the RMS offset decay.                                                        |    No    | `200`         |
| `VL_OFFSET_DECAY_MIN`            | The floor for the decayed RMS offset.                                                                   |    No    | `40`          |

## 🗣️ Barge-In Control (Advanced)

Settings to control the agent's ability to be interrupted by the caller.

| Variable                         | Description                                                                                             | Required | Default Value |
| -------------------------------- | ------------------------------------------------------------------------------------------------------- | :------: | ------------- |
| `VL_BARGE_IN_ENABLED`            | Feature flag to enable or disable barge-in detection.                                                   |    No    | `true`        |
| `VL_BARGE_IN_OFFSET`             | A sensitive RMS offset used for detecting barge-in while the agent is speaking.                         |    No    | `40`          |
| `VL_BARGE_IN_CONSECUTIVE_FRAMES` | Number of consecutive frames above the barge-in threshold required to trigger an interruption.          |    No    | `3`           |

## ⚙️ Media Streaming & Debugging (Advanced)

Low-level settings for controlling the media stream and debugging.

| Variable                       | Description                                                                                             | Required | Default Value         |
| ------------------------------ | ------------------------------------------------------------------------------------------------------- | :------: | --------------------- |
| `MEDIA_BIDIRECTIONAL`          | Use bidirectional media streaming with ACS.                                                             |    No    | `true`                |
| `MEDIA_AUDIO_CHANNEL_TYPE`     | The audio channel type from ACS. Can be `mixed` or `unmixed`.                                           |    No    | `mixed`               |
| `MEDIA_DUMP_WAV`               | If `true`, saves the incoming call audio to a WAV file for debugging.                                   |    No    | `false`               |
| `MEDIA_WAV_PATH`               | The file path where the debug WAV file will be saved.                                                   |    No    | `media_capture.wav`   |
| `VL_LOG_FIRST_COMMIT`          | If `true`, emits a structured log with detailed timing information for the first audio commit.          |    No    | `true`                |
