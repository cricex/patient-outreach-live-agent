#!/usr/bin/env bash
# start_call.sh — helper to POST /call/start using curl
# Requires: bash, curl, scripts/load_env.sh
# Usage: start_call.sh (optional overrides by editing JSON payload)
set -euo pipefail

# Get the directory of the script itself to reliably source other scripts
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Source the environment loader script to get APP_BASE_URL
source "$SCRIPT_DIR/load_env.sh"

# Check if APP_BASE_URL is set
if [[ -z "${APP_BASE_URL:-}" ]]; then
  echo "ERROR: APP_BASE_URL is not set. Make sure it is in your .env file."
  exit 1
fi

echo "Starting call using APP_BASE_URL: $APP_BASE_URL"
echo "---"

# Run the curl command to start the call.
#
# The JSON payload below determines which parameters are sent.
# - "target_phone_number": null  (uses the phone number from your .env file)
# - "target_phone_number": "+1..." (overrides the .env file)
# - "system_prompt": null (uses the system prompt from your .env file)
# - "system_prompt": "You are a pirate." (overrides the .env file)
#
# The default below uses the values from your .env file for a non-breaking change.
curl -v -X POST "$APP_BASE_URL/call/start" \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "target_phone_number": null,
  "system_prompt": null
}
EOF
