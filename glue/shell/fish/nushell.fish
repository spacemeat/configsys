# nushell: alias to the tarball-installed binary (versioned subdir / candidate paths). No-ops where native.
set -l loc (configsys location nushell 2>/dev/null)
if test -n "$loc"
    set -l bin ""
    for c in $loc/nu-*-x86_64-unknown-linux-*/nu
        test -x "$c"; and set bin "$c"
    end
    test -n "$bin"; and alias nu "$bin"
end
