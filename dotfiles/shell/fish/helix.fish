# helix: alias to the tarball-installed binary (versioned subdir / candidate paths). No-ops where native.
set -l loc (configsys location helix 2>/dev/null)
if test -n "$loc"
    set -l bin ""
    for c in $loc/helix-*-x86_64-linux/hx
        test -x "$c"; and set bin "$c"
    end
    test -n "$bin"; and alias hx "$bin"
end
