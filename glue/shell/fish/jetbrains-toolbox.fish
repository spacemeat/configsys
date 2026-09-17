# jetbrains-toolbox: alias to the tarball-installed binary (versioned subdir / candidate paths). No-ops where native.
set -l loc (configsys location jetbrains-toolbox 2>/dev/null)
if test -n "$loc"
    set -l bin ""
    for c in $loc/jetbrains-toolbox-*/jetbrains-toolbox $loc/jetbrains-toolbox
        test -x "$c"; and set bin "$c"
    end
    test -n "$bin"; and alias jetbrains-toolbox "$bin"
end
