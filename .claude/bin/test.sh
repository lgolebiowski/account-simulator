#!/usr/bin/env bash
# Run pytest (extra arguments are passed through). The exit code is pytest's own.
#   .claude/bin/test.sh                      full suite
#   .claude/bin/test.sh tests/test_ui.py -q  one file
# Refuses to run, with a clear message, if Postgres isn't up: a run that never touched the
# database must not be mistaken for a pass.
here=$(cd "$(dirname "$0")" && pwd)
source "$here/_env.sh"
if ! "$bin/python" -c "import socket; socket.create_connection(('localhost', 5434), 2).close()" 2>/dev/null; then
  echo "Postgres is not reachable on localhost:5434. Start it: docker compose up -d --wait" >&2
  exit 3
fi
cd "$root" && exec "$bin/python" -m pytest -q "$@"
