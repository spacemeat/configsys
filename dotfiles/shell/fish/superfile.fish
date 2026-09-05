# superfile: alias to the tarball-installed binary (versioned subdir / candidate paths). No-ops where native.
set -l loc (configsys location superfile 2>/dev/null)
if test -n "$loc"
    set -l bin ""
    for c in $loc/dist/superfile-linux-*/spf
        test -x "$c"; and set bin "$c"
    end
    test -n "$bin"; and alias spf "$bin"
end
