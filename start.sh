#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.10+ and try again."
  exit 1
fi

if [ ! -d ".venv" ]; then
  if ! python3 -m venv .venv; then
    echo "Could not create .venv. On Debian/Ubuntu install: sudo apt install python3-venv"
    exit 1
  fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate

REQ_HASH_FILE=".venv/.requirements.sha256"
REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"

if [ ! -f "$REQ_HASH_FILE" ] || [ "$(cat "$REQ_HASH_FILE")" != "$REQ_HASH" ]; then
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  printf "%s" "$REQ_HASH" > "$REQ_HASH_FILE"
fi

exec python main.py "$@"
