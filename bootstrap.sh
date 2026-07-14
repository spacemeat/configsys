#!/usr/bin/env bash
# configsys bootstrap — the minimal bash layer. Ensures python3 >= 3.10, a repo
# .venv, and humon, then hands off to the python app. Idempotent: safe to re-run.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

PY="${PYTHON:-python3}"

# 1. python3 >= 3.10
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "configsys: python3 not found — install python >= 3.10 and retry." >&2
    exit 1
fi
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "configsys: python >= 3.10 required (found: $("$PY" -V 2>&1))." >&2
    exit 1
fi

# 2. virtual environment
VENV="$here/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo "configsys: creating virtual environment (.venv)..." >&2
    "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"

# 3. humon
if ! "$VPY" -c 'import humon' >/dev/null 2>&1; then
    echo "configsys: installing humon..." >&2
    "$VENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
    "$VENV/bin/pip" install -q humon
fi

# 4. hand off to the app (pass all args through)
exec "$VPY" -m configsys "$@"
