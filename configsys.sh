#!/usr/bin/env bash
# configsys.sh — the minimal bash layer. Ensures python3 >= 3.10, a repo
# .venv, and humon, then hands off to the python app. Idempotent: safe to re-run.
set -euo pipefail

# the repo is where this script REALLY lives — through a symlink too (`ln -s …/configsys.sh
# ~/.local/bin/configsys`), else the venv would be built next to the link and the package not found
src="${BASH_SOURCE[0]}"
src="$(readlink -f -- "$src" 2>/dev/null || printf '%s' "$src")"
here="$(cd "$(dirname "$src")" && pwd)"
# relative paths on the command line (`plugin add .`, `--home ./sandbox`) mean YOUR directory: the
# app changes back to it first thing (configsys/__main__.py), after the import found the package here
export CONFIGSYS_INVOKED_CWD="$PWD"
cd "$here"

# 1. python3 >= 3.10. $PYTHON if you set it; else the first of python3, python3.14 … python3.10 that
# is new enough (EL 9 and Amazon Linux 2023 ship python3 = 3.9 beside a newer python3.1x).
_py_ok() { "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }
if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
else
    PY=""
    for cand in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
        if command -v "$cand" >/dev/null 2>&1 && _py_ok "$cand"; then PY="$cand"; break; fi
    done
fi
if [ -z "$PY" ] || ! command -v "$PY" >/dev/null 2>&1 || ! _py_ok "$PY"; then
    found="$( { command -v python3 >/dev/null 2>&1 && python3 -V 2>&1; } || echo 'no python3')"
    hint="install python >= 3.10"
    if command -v dnf >/dev/null 2>&1; then hint="sudo dnf install python3.12   (EL 9: also python3.12-devel to build humon)"
    elif command -v apt-get >/dev/null 2>&1; then hint="sudo apt-get install python3"
    elif command -v zypper >/dev/null 2>&1; then hint="sudo zypper install python311"
    fi
    echo "configsys: python >= 3.10 required (found: $found)." >&2
    echo "  install one — $hint — or point configsys at one: PYTHON=/path/to/python3.1x configsys …" >&2
    exit 1
fi

# 2. virtual environment. Debian/Ubuntu (incl. Pop!_OS) ship `python3` WITHOUT venv/ensurepip —
# that's the separate pythonX.Y-venv package — and a failed `python -m venv` still leaves a
# .venv/bin/python behind with no pip. So: require ensurepip up front, and judge an existing venv
# by whether its pip WORKS (not whether bin/python exists), rebuilding a half-made one.
VENV="$here/.venv"
VPY="$VENV/bin/python"
# FAST path first — this runs on EVERY `configsys` call (the shell glue calls it at startup): one
# interpreter start that only LOCATES pip/humon/packaging (find_spec, no imports; ~40ms). Only if
# that fails do we pay for the real repair below (`-m pip --version` alone is ~0.7s).
_venv_ok() {
    "$VPY" -c 'import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ("pip", "humon", "packaging")) else 1)' >/dev/null 2>&1
}
if _venv_ok; then
    exec "$VPY" -m configsys "$@"
fi
# a shell START (the glue preludes refreshing their location cache) never repairs: no venv rebuild,
# no pip compile, no `sudo apt-get` behind a hidden stderr while a terminal opens — the prelude keeps
# its cached values, and the next `configsys` you run yourself repairs it visibly (A15)
if [ -n "${CONFIGSYS_NO_BOOTSTRAP:-}" ]; then
    exit 75
fi
# one repair at a time: two terminals opening together must not `venv --clear` the same .venv
if command -v flock >/dev/null 2>&1 && [ -z "${_CONFIGSYS_REPAIR_LOCKED:-}" ]; then
    exec env _CONFIGSYS_REPAIR_LOCKED=1 flock "$VENV.lock" "$src" "$@"
fi
if _venv_ok; then                      # another process repaired it while we waited for the lock
    exec "$VPY" -m configsys "$@"
fi
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
    if ! "$VPY" -m pip install -q humon packaging; then
        # humon ships as SOURCE only (a C extension), so pip compiles it: that needs a C compiler and
        # the Python headers, which minimal installs/containers lack. Name the fix for this distro.
        hint="a C compiler and the Python development headers"
        if command -v apt-get >/dev/null 2>&1; then hint="sudo apt-get install build-essential python3-dev"
        elif command -v dnf >/dev/null 2>&1; then hint="sudo dnf install gcc python3-devel"
        elif command -v pacman >/dev/null 2>&1; then hint="sudo pacman -S gcc"
        elif command -v zypper >/dev/null 2>&1; then hint="sudo zypper install gcc python3-devel"
        elif command -v apk >/dev/null 2>&1; then hint="sudo apk add build-base python3-dev"
        elif command -v xbps-install >/dev/null 2>&1; then hint="sudo xbps-install gcc python3-devel"
        fi
        echo "configsys: building humon failed — it compiles from source; install: $hint" >&2
        exit 1
    fi
fi

# 4. hand off to the app (pass all args through)
exec "$VPY" -m configsys "$@"
