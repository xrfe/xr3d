#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
    echo 'Run install-xr3d-server.sh first.' >&2
    exit 1
fi
exec .venv/bin/python -m backend.serve --host 0.0.0.0 "$@"
