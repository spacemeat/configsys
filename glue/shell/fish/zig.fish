# zig: add the tarball-installed dir to PATH (unpacks into a versioned subdir). No-op where native.
set -l loc (configsys location zig 2>/dev/null)
if test -n "$loc"
    set -l dir ""
    for d in $loc/zig-linux-*
        test -d "$d"; and set dir "$d"
    end
    test -n "$dir"; and fish_add_path -g "$dir"
end
