# fzf: resolve the binary (native on PATH, else the tarball under the managed dir) and load its
# bash key-bindings + completion. `fzf --bash` needs fzf >= 0.48.
_fzf=$(command -v fzf 2>/dev/null)
if [ -z "$_fzf" ]; then
    _fd=$(configsys location fzf 2>/dev/null)
    [ -n "$_fd" ] && _fzf=$(ls -1 "$_fd"/fzf 2>/dev/null | tail -1)
    [ -x "$_fzf" ] && alias fzf="$_fzf"
    unset _fd
fi
[ -x "$_fzf" ] && eval "$("$_fzf" --bash)" 2>/dev/null
unset _fzf
