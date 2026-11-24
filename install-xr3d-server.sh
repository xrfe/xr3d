#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
    if ! command -v python3.12 >/dev/null 2>&1; then
        echo 'Install Python 3.12 and its venv package, then run this script again.' >&2
        exit 1
    fi
    python3.12 -m venv .venv
fi
exec .venv/bin/python -m backend.install "$@"
