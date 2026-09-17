# btop: alias to the tarball-installed binary (versioned subdir / candidate paths). No-ops where native.
set -l loc (configsys location btop 2>/dev/null)
if test -n "$loc"
    set -l bin ""
    for c in $loc/btop/bin/btop $loc/bin/btop
        test -x "$c"; and set bin "$c"
    end
    test -n "$bin"; and alias btop "$bin"
end
