#!/usr/bin/env sh
# Start the Fabrique workspace daemon on this computer (macOS or Linux).
#
# The daemon is what lets the agents work in the folders where you cloned your
# GitHub/GitLab projects: it lists folders for the picker, checks a project,
# writes the agents' files and runs commands there. It connects to the NATS
# server of the Docker stack (nats://localhost:4222, override with NATS_URL)
# and keeps retrying until it is up.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DAEMON_DIR="$ROOT/vscode-daemon"
VENV="$DAEMON_DIR/.venv"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.9 or newer is required (or set PYTHON=/path/to/python3)." >&2
  exit 1
fi

if [ ! -x "$VENV/bin/python" ]; then
  if ! "$PYTHON" -m venv "$VENV"; then
    echo "Could not create a virtual environment. On Ubuntu/Debian: sudo apt install python3-venv" >&2
    exit 1
  fi
fi

"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r "$DAEMON_DIR/requirements.txt"

NATS_URL="${NATS_URL:-nats://localhost:4222}"
export NATS_URL
exec "$VENV/bin/python" "$DAEMON_DIR/daemon.py"
