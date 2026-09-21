# tuxedo: alias to the tarball-installed binary (versioned subdir). No-ops where native.
set -l loc (configsys location tuxedo 2>/dev/null)
if test -n "$loc"
    set -l bin ""
    for c in $loc/tuxedo-*/tuxedo
        test -x "$c"; and set bin "$c"
    end
    test -n "$bin"; and alias tuxedo "$bin"
end
