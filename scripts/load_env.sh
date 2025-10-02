#!/usr/bin/env bash
# load_env.sh — reliably load .env values into the current shell (supports overrides)
# Usage: source scripts/load_env.sh [optional-extra-env]

# This script must be sourced so that exported variables land in the caller's environment.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "This script must be sourced (use 'source scripts/load_env.sh')." >&2
    exit 1
fi

# Resolve project root and candidate env files.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"

declare -a ENV_FILES=()

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    ENV_FILES+=("$PROJECT_ROOT/.env")
fi

if [[ -f "$PROJECT_ROOT/.env.local" ]]; then
    ENV_FILES+=("$PROJECT_ROOT/.env.local")
fi

# Allow callers to specify an additional env file path (highest precedence).
if [[ $# -ge 1 ]]; then
    for extra in "$@"; do
        if [[ -f "$extra" ]]; then
            ENV_FILES+=("$extra")
        else
            echo "Warning: extra env file '$extra' not found; skipping." >&2
        fi
    done
fi

if [[ ${#ENV_FILES[@]} -eq 0 ]]; then
    echo "Warning: no .env files found under $PROJECT_ROOT. Nothing was exported." >&2
    return 0
fi

if ! command -v python >/dev/null 2>&1; then
    echo "Error: python executable not found in PATH; cannot parse .env files." >&2
    return 1
fi

# Use python + python-dotenv for robust parsing (quotes, multiline, comments, etc.).
if ! EXPORT_SNIPPET="$(python - "${ENV_FILES[@]}" <<'PY'
import os
import shlex
import sys
from pathlib import Path

try:
        from dotenv import dotenv_values
except ModuleNotFoundError as exc:
        print(f"python-dotenv is required but not installed: {exc}", file=sys.stderr)
        sys.exit(2)

env_files = sys.argv[1:]
merged: dict[str, str] = {}

for raw_path in env_files:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
                continue
        data = dotenv_values(path)
        for key, value in data.items():
                if value is None:
                        continue
                merged[key] = value

if not merged:
        sys.exit(0)

for key, value in merged.items():
        print(f"export {key}={shlex.quote(value)}")
PY
"; then
    status=$?
    if [[ $status -eq 2 ]]; then
        echo "Error: python-dotenv package is required. Install it with 'pip install python-dotenv'." >&2
    fi
    return $status
fi

if [[ -n "$EXPORT_SNIPPET" ]]; then
    eval "$EXPORT_SNIPPET"
    echo "Loaded environment variables from:"
    for file in "${ENV_FILES[@]}"; do
        echo "  - $file"
    done
fi

return 0
