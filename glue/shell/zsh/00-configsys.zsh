# Make `configsys` callable from scripts (so other snippets can run it). Aliases do NOT expand in non-interactive
# shells, so this is a function. It defers to a real `configsys` on PATH (e.g. a pipx install)
# and only otherwise falls back to the clone's launcher, found in this order: $CONFIGSYS_LAUNCHER;
# the launcher path the glue driver records on every shell hookup (`<state>/launcher` — wherever the
# clone actually lives); else <src>/configsys/configsys.sh under $HOME (per CONFIGSYS_SRC_DIR).
if ! command -v configsys >/dev/null 2>&1; then
    configsys() {
        local launcher="${CONFIGSYS_LAUNCHER:-}"
        local rec="${CONFIGSYS_STATE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/configsys}/launcher"
        [ -z "$launcher" ] && [ -r "$rec" ] && launcher=$(<"$rec")
        [ -z "$launcher" ] && launcher="$HOME/${CONFIGSYS_SRC_DIR:-src}/configsys/configsys.sh"
        if [ -x "$launcher" ]; then
            "$launcher" "$@"
        else
            echo "configsys: launcher not found ($launcher) — set CONFIGSYS_LAUNCHER, or install" \
                "configsys on your PATH" >&2
            return 127
        fi
    }
fi

# cfs: interactive shorthand for configsys (the same command in every configsys shell).
alias cfs=configsys

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
    # CONFIGSYS_NO_BOOTSTRAP: a shell start never repairs the launcher's venv (no hidden sudo); on any
    # failure keep the stale cache rather than an empty one
    _CS_LOCS=$(export CONFIGSYS_NO_BOOTSTRAP=1; configsys location --all 2>/dev/null) \
        || { [ -f "$_cs_cache" ] && _CS_LOCS=$(<"$_cs_cache"); }
fi
unset _cs_cache
# loaded ONCE into an associative array: a lookup is a hash hit, not a scan of the whole cache per call
typeset -gA _CS_LOC
() {
    local _l
    for _l in ${(f)_CS_LOCS}; do
        [[ $_l == *$'\t'* ]] && _CS_LOC[${_l%%$'\t'*}]=${_l#*$'\t'}
    done
}
cs_loc() {
    (( ${+_CS_LOC[$1]} )) && print -r -- "${_CS_LOC[$1]}"
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
