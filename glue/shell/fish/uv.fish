# uv: tarball install dir (never-auto binding; no-op for the pipx/native default) + `uv tool` bin.
set -l loc (configsys location uv 2>/dev/null)
if test -n "$loc"
    set -l dir ""
    for d in $loc/uv-*
        test -d "$d"; and set dir "$d"
    end
    if test -n "$dir"
        fish_add_path -g "$dir"
    else if test -x "$loc/uv"
        fish_add_path -g "$loc"
    end
end
test -d "$HOME/.local/bin"; and fish_add_path -g "$HOME/.local/bin"
