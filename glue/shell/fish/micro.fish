# micro: alias to the tarball-installed binary (versioned subdir / candidate paths). No-ops where native.
set -l loc (configsys location micro 2>/dev/null)
if test -n "$loc"
    set -l bin ""
    for c in $loc/micro-*/micro
        test -x "$c"; and set bin "$c"
    end
    test -n "$bin"; and alias micro "$bin"
end
