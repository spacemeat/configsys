# fzf: load fish key-bindings + completion. `fzf --fish` needs fzf >= 0.48 (older fzf has no fish
# integration flag — install a current fzf or pin the tarball). Resolve the tarball binary if fzf
# isn't on PATH.
set -l fzf (command -v fzf 2>/dev/null)
if test -z "$fzf"
    set -l loc (configsys location fzf 2>/dev/null)
    if test -n "$loc"; and test -x "$loc/fzf"
        set fzf "$loc/fzf"
        alias fzf "$loc/fzf"
    end
end
test -x "$fzf"; and "$fzf" --fish 2>/dev/null | source
