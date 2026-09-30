# Make `configsys` callable from scripts/functions (so other conf.d snippets can run it). Defers to a real `configsys` on PATH (e.g. a pipx
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

# cs_loc <component>: the managed install location of a component ("" if none/native) — what the
# tarball/appImage/source snippets use to find their off-PATH binaries. A `configsys location <x>` per
# snippet is a whole configsys process, and ~50 snippets made startup take ~20s. So, like the other
# shells: configsys writes a `<comp>\t<path>` cache (glue-locations.tsv, refreshed by `location --all`,
# invalidated on a pin/pick edit or plugin sync); startup reads it once, and only a cold/stale (>1h)
# cache spawns ONE `configsys location --all` (which rewrites it). Covers this machine's picks.
set -l _cs_cache (set -q CONFIGSYS_STATE_DIR; and echo $CONFIGSYS_STATE_DIR; or echo (set -q XDG_CONFIG_HOME; and echo $XDG_CONFIG_HOME; or echo $HOME/.config)/configsys)/glue-locations.tsv
if test -f $_cs_cache; and test -n (find $_cs_cache -mmin -60 2>/dev/null | string collect)
    set -g __cs_locs (cat $_cs_cache)
else
    set -g __cs_locs (configsys location --all 2>/dev/null)
end
function cs_loc --argument-names name
    for line in $__cs_locs
        set -l kv (string split -m 1 \t -- $line)
        if test "$kv[1]" = "$name"
            echo $kv[2]
            return 0
        end
    end
end

# cs_cached <key> <tool> <cmd…>: <cmd>'s output, CACHED in ~/.cache/configsys/glue-eval/<key> and
# regenerated only when <tool>'s executable is newer than the cache (an upgrade refreshes it) — for init
# scripts that cost 100ms+ per startup. (`command test`: fish 3.3's builtin test has no -nt.) A
# failing/empty <cmd> caches nothing and returns 1.
function cs_cached --argument-names key tool
    set -l bin (command -v $tool 2>/dev/null); or return 1
    set -l dir (set -q XDG_CACHE_HOME; and echo $XDG_CACHE_HOME; or echo $HOME/.cache)/configsys/glue-eval
    set -l f $dir/$key
    if not test -s $f; or command test $bin -nt $f
        mkdir -p $dir; and $argv[3..-1] > $f.tmp 2>/dev/null; and test -s $f.tmp; and mv -f $f.tmp $f
        or begin
            rm -f $f.tmp
            return 1
        end
    end
    cat $f
end
