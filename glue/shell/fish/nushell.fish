# nushell: put the tarball-installed `nu` on PATH (versioned target-triple subdir) so `nu` execs AND
# `which nu` detects it. MUST be on PATH, not an alias — configsys's detection is `which nu`, blind to
# aliases. `find` (quoted patterns) avoids fish's unmatched-glob error. No-op where nu is native.
set -l loc (configsys location nushell 2>/dev/null)
if test -n "$loc"
    set -l nubin (find "$loc" -maxdepth 2 -type f -name nu -path '*/nu-*-x86_64-unknown-linux-*/nu' 2>/dev/null | head -1)
    test -n "$nubin"; and test -x "$nubin"; and fish_add_path -gp (dirname "$nubin")
end
