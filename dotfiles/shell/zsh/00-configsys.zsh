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
