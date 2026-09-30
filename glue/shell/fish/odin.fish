# Odin: tarball unpacks under the app dir (root or a versioned subdir; no-op when native).
set -l loc (cs_loc odin)
if test -n "$loc"
    set -l dir ""
    for d in $loc/odin-linux-*
        test -d "$d"; and set dir "$d"
    end
    if test -n "$dir"
        fish_add_path -g "$dir"
    else if test -x "$loc/odin"
        fish_add_path -g "$loc"
    end
end
