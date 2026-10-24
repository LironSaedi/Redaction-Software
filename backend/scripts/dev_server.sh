#!/bin/sh
# Local development server with a throwaway data folder (never your real case data).
#   scripts/dev_server.sh            -> http://127.0.0.1:8600 , data in /tmp/obscura-dev
cd "$(dirname "$0")/.."
export OBSCURA_DATA="${OBSCURA_DATA:-/tmp/obscura-dev}"
export OBSCURA_WATCHER=0
export OBSCURA_BLOCK_NET=1
exec .venv/bin/python -m obscura.main --port "${OBSCURA_PORT:-8600}" "$@"
