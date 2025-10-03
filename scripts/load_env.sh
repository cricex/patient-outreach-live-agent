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

_fallback_source_env_files() {
    local file
    local had_error=0

    set -a
    for file in "${ENV_FILES[@]}"; do
        if [[ ! -r "$file" ]]; then
            echo "Warning: env file '$file' is not readable; skipping." >&2
            continue
        fi
        # shellcheck disable=SC1090
        if ! source "$file"; then
            echo "Warning: failed to source env file '$file'." >&2
            had_error=1
        fi
    done
    set +a

    return $had_error
}

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

LOADED_VIA=${LOADED_VIA:-}
EXPORT_SNIPPET=""

if command -v python >/dev/null 2>&1; then
    if EXPORT_SNIPPET="$(python "$SCRIPT_DIR/_load_env.py" "${ENV_FILES[@]}" 2> >(cat >&2))"; then
        LOADED_VIA="python"
    else
        status=$?
        if [[ $status -eq 2 ]]; then
            echo "Warning: python-dotenv package is required for advanced parsing. Falling back to shell sourcing." >&2
        else
            echo "Warning: python-based env loader failed with status $status. Falling back to shell sourcing." >&2
        fi
        EXPORT_SNIPPET=""
    fi
else
    echo "Warning: python executable not found; falling back to shell sourcing." >&2
fi

if [[ "$LOADED_VIA" == "python" ]]; then
    if [[ -n "$EXPORT_SNIPPET" ]]; then
        eval "$EXPORT_SNIPPET"
    fi
elif ! _fallback_source_env_files; then
    echo "Error: failed to load one or more env files using shell fallback." >&2
    return 1
fi

echo "Loaded environment variables from:"
for file in "${ENV_FILES[@]}"; do
    echo "  - $file"
done

if [[ "$LOADED_VIA" == "python" ]]; then
    return 0
fi

return 0
