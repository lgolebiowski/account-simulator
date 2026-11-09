#!/usr/bin/env bash
# Static checks: ruff (bugs), bandit (security smells in app code), pip-audit (known-vulnerable
# dependencies). Runs all three even if one fails; exits non-zero if any did.
here=$(cd "$(dirname "$0")" && pwd)
source "$here/_env.sh"
cd "$root" || exit 2
status=0
for tool in ruff bandit pip-audit; do
  [ -x "$bin/$tool" ] || { echo "== $tool: NOT INSTALLED (pip install -r requirements-dev.txt)"; status=1; }
done
echo "== ruff";      "$bin/ruff" check . || status=1
echo "== bandit";    "$bin/bandit" -q -r bankapp cli.py || status=1
echo "== pip-audit"; "$bin/pip-audit" -r requirements.txt || status=1
exit $status
