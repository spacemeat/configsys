# fzf: load fish key-bindings + completion. `fzf --fish` needs fzf >= 0.48 (older fzf has no fish
# integration flag — install a current fzf or pin the tarball). Resolve the tarball binary if fzf
# isn't on PATH (that alias is the tool's entry point, so scripts get it too; the bindings are interactive).
set -l fzf (command -v fzf 2>/dev/null)
if test -z "$fzf"
    set -l loc (cs_loc fzf)
    if test -n "$loc"; and test -x "$loc/fzf"
        set fzf "$loc/fzf"
        alias fzf "$loc/fzf"
    end
end
status is-interactive; and test -x "$fzf"; and "$fzf" --fish 2>/dev/null | source
