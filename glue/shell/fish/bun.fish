# Bun: tarball install dir (zip -> bun-linux-*/ subdir; no-op when native) + global bin.
set -l loc (configsys location bun 2>/dev/null)
if test -n "$loc"
    set -l dir ""
    for d in $loc/bun-linux-*
        test -d "$d"; and set dir "$d"
    end
    test -n "$dir"; and fish_add_path -g "$dir"
end
set -gx BUN_INSTALL "$HOME/.bun"
test -d "$BUN_INSTALL/bin"; and fish_add_path -ga "$BUN_INSTALL/bin"
