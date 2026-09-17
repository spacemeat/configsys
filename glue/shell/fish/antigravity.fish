# antigravity: alias to the tarball-installed binary (versioned subdir / candidate paths). No-ops where native.
set -l loc (configsys location antigravity 2>/dev/null)
if test -n "$loc"
    set -l bin ""
    for c in $loc/antigravity $loc/*/antigravity $loc/*/bin/antigravity
        test -x "$c"; and set bin "$c"
    end
    test -n "$bin"; and alias antigravity "$bin"
end
