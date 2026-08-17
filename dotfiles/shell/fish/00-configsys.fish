# Make `configsys` callable from scripts/functions (so other conf.d snippets can do e.g.
# `set -gx FOO (configsys location foo)/bin`). Defers to a real `configsys` on PATH (e.g. a pipx
# install) and only otherwise falls back to the clone's launcher. Override the launcher with
# CONFIGSYS_LAUNCHER; the default assumes the clone lives at <src>/configsys (per CONFIGSYS_SRC_DIR).
if not command -v configsys >/dev/null 2>&1
    function configsys
        set -l srcdir $CONFIGSYS_SRC_DIR
        test -z "$srcdir"; and set srcdir src
        set -l launcher $CONFIGSYS_LAUNCHER
        test -z "$launcher"; and set launcher "$HOME/$srcdir/configsys/configsys.sh"
        if test -x "$launcher"
            $launcher $argv
        else
            echo "configsys: launcher not found ($launcher) — set CONFIGSYS_LAUNCHER, or install configsys on your PATH" >&2
            return 127
        end
    end
end

alias cf="~/src/configsys/configsys.sh"
