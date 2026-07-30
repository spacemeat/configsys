# configsys — standard install layout ("config for configsys"). configsys uses these dirs to
# decide WHERE it puts things; exporting them here keeps your shell and configsys in agreement.
# Override any value in your own shell config BEFORE this file runs to relocate a whole class of
# installs; configsys falls back to these same defaults when a variable is unset.
#
# An install location is:  <scope base>/<category>/<name>
#   category (set below):  apps/ for self-contained apps, sdks/ for SDKs+libs, src/ for builds
#   scope base (advanced): your home for user-scope, /opt for system-scope
: "${CONFIGSYS_APP_DIR:=apps}"          # tarball/appImage apps -> ~/apps/<name>
: "${CONFIGSYS_SDK_DIR:=sdks}"          # SDKs and libraries    -> ~/sdks/<name>
: "${CONFIGSYS_SRC_DIR:=src}"           # source-build trees    -> ~/src/<name>
export CONFIGSYS_APP_DIR CONFIGSYS_SDK_DIR CONFIGSYS_SRC_DIR

# Scope bases (advanced) — where user/system installs root. Defaults: your home and /opt.
# Uncomment to relocate everything (e.g. onto another volume):
#   export CONFIGSYS_USERSCOPE_DIR="$HOME"  CONFIGSYS_SYSTEMSCOPE_DIR=/opt

# Make `configsys` callable from scripts (so other bash.d snippets can do
# `export FOO="$(configsys location foo)/bin"`). Aliases do NOT expand in non-interactive
# shells, so this is a function. It defers to a real `configsys` on PATH (e.g. a pipx install)
# and only otherwise falls back to the clone's launcher. Override the launcher with
# CONFIGSYS_LAUNCHER; the default assumes the clone lives at <src>/configsys (per CONFIGSYS_SRC_DIR).
if ! command -v configsys >/dev/null 2>&1; then
    configsys() {
        local launcher="${CONFIGSYS_LAUNCHER:-$HOME/${CONFIGSYS_SRC_DIR:-src}/configsys/configsys.sh}"
        if [ -x "$launcher" ]; then
            "$launcher" "$@"
        else
            echo "configsys: launcher not found ($launcher) — set CONFIGSYS_LAUNCHER, or install" \
                 "configsys on your PATH" >&2
            return 127
        fi
    }
fi

alias cf="~/src/configsys/configsys.sh"
