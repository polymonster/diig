#!/usr/bin/env bash
#
# Create the diig Python venv and install dependencies.
# Safe to re-run: it reuses the existing venv and just updates packages.
#
# Usage:
#   ./setup.sh          # create/update ./.venv and install deps
#
# After it finishes, activate with:
#   source scrape/.venv/bin/activate

set -euo pipefail

# Directory this script lives in (so it works no matter where you call it from).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Pick a python3. Override by exporting PYTHON=/path/to/python3 before running.
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "error: '$PYTHON' not found. Install Python 3 or set PYTHON=/path/to/python3." >&2
    exit 1
fi

echo ">> using $("$PYTHON" --version) at $(command -v "$PYTHON")"

if [ ! -d "$VENV_DIR" ]; then
    echo ">> creating venv at $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
else
    echo ">> reusing existing venv at $VENV_DIR"
fi

# Use the venv's python directly; no need to activate inside the script.
VENV_PY="$VENV_DIR/bin/python"

echo ">> upgrading pip"
"$VENV_PY" -m pip install --upgrade pip

echo ">> installing requirements"
"$VENV_PY" -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo ">> done. activate the env with:"
echo "     source scrape/.venv/bin/activate"
