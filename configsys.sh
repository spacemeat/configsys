#!/usr/bin/env bash
# configsys.sh — the minimal bash layer. Ensures python3 >= 3.10, a repo
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

# 2. virtual environment. Debian/Ubuntu (incl. Pop!_OS) ship `python3` WITHOUT venv/ensurepip —
# that's the separate pythonX.Y-venv package — and a failed `python -m venv` still leaves a
# .venv/bin/python behind with no pip. So: require ensurepip up front, and judge an existing venv
# by whether its pip WORKS (not whether bin/python exists), rebuilding a half-made one.
VENV="$here/.venv"
VPY="$VENV/bin/python"
if ! "$VPY" -m pip --version >/dev/null 2>&1; then
    if ! "$PY" -c 'import ensurepip' >/dev/null 2>&1; then
        pyver="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
        if command -v apt-get >/dev/null 2>&1; then
            echo "configsys: python venv support missing — installing python${pyver}-venv (sudo)..." >&2
            sudo apt-get install -y "python${pyver}-venv"
        else
            echo "configsys: python's venv/ensurepip module is missing — install your distro's" \
                 "python venv package and retry." >&2
            exit 1
        fi
    fi
    if [ -e "$VENV" ]; then
        echo "configsys: existing .venv has no working pip — rebuilding it..." >&2
        "$PY" -m venv --clear "$VENV"
    else
        echo "configsys: creating virtual environment (.venv)..." >&2
        "$PY" -m venv "$VENV"
    fi
fi

# 3. python deps: humon (the .hu format) + packaging (PEP 440 version logic)
if ! "$VPY" -c 'import humon, packaging' >/dev/null 2>&1; then
    echo "configsys: installing python dependencies (humon, packaging)..." >&2
    "$VPY" -m pip install -q --upgrade pip || true
    "$VPY" -m pip install -q humon packaging
fi

# 4. hand off to the app (pass all args through)
exec "$VPY" -m configsys "$@"
