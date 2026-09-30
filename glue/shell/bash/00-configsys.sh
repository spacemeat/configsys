# Make `configsys` callable from scripts (so other snippets can run it). Aliases do NOT expand in non-interactive
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

# cs_loc <component>: the managed install location of a component ("" if none/native) — what the
# tarball/appImage/source snippets use to find their off-PATH binaries. A `configsys location <x>` per
# snippet is a whole configsys process (~0.8s), and ~50 snippets made startup take most of a MINUTE.
# So, like the nu/elvish glue: configsys writes a `<comp>\t<path>` cache (glue-locations.tsv, refreshed
# by `location --all` and invalidated on a pin/pick edit or plugin sync); a normal startup reads it
# once (~1ms), and only a cold/stale (>1h) cache spawns ONE `configsys location --all` (which rewrites
# it). Covers this machine's picks. Lookups are then in-shell.
_cs_cache="${CONFIGSYS_STATE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/configsys}/glue-locations.tsv"
if [ -f "$_cs_cache" ] && [ -n "$(find "$_cs_cache" -mmin -60 2>/dev/null)" ]; then
    _CS_LOCS=$(<"$_cs_cache")
else
    _CS_LOCS=$(configsys location --all 2>/dev/null)
fi
unset _cs_cache
cs_loc() {
    local _n _p
    while IFS=$'\t' read -r _n _p; do
        [ "$_n" = "$1" ] && { printf '%s\n' "$_p"; return 0; }
    done <<< "$_CS_LOCS"
    return 0
}

# cs_cached <key> <tool> <cmd…>: <cmd>'s output, CACHED in ~/.cache/configsys/glue-eval/<key> and
# regenerated only when <tool>'s executable is newer than the cache (so an upgrade refreshes it). For
# init scripts that cost 100ms+ per startup (`pyenv init -`, `luarocks path --lr-path`, ruby's gem dir):
# a cache hit is a file-mtime test + a read. The output must not embed values that change without the
# tool changing (e.g. `luarocks path` bakes in the whole current $PATH — cache --lr-path/--lr-cpath).
# A failing/empty <cmd> caches nothing and returns 1.
cs_cached() {
    local key=$1 tool=$2 bin dir f
    shift 2
    bin=$(command -v "$tool" 2>/dev/null) || return 1
    dir="${XDG_CACHE_HOME:-$HOME/.cache}/configsys/glue-eval"
    f="$dir/$key"
    if [ ! -s "$f" ] || [ "$bin" -nt "$f" ]; then
        { mkdir -p "$dir" && "$@" > "$f.tmp" 2>/dev/null && [ -s "$f.tmp" ] && mv -f "$f.tmp" "$f"; } \
            || { rm -f "$f.tmp"; return 1; }
    fi
    printf '%s\n' "$(<"$f")"
}
