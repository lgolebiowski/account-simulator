# Sourced by test.sh and audit.sh: find the repo root and a Python with the project's packages.
# Works from the main checkout and from a git worktree (which has no .venv of its own).
root=$(git rev-parse --show-toplevel 2>/dev/null) || root=$(pwd)
common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
main_root=${common:+$(dirname "$common")}
bin=""
for base in "$root" "$main_root"; do
  [ -n "$base" ] && [ -x "$base/.venv/bin/python" ] && { bin="$base/.venv/bin"; break; }
done
if [ -z "$bin" ]; then
  echo "No .venv found. Create it: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 2
fi
