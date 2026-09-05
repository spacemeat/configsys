# fzf: resolve the binary (native on PATH, else the tarball under the managed dir), then load its
# zsh integration. The unified `fzf --zsh` needs fzf >= 0.48; older fzf ships SEPARATE key-bindings
# + completion scripts — check the version and pick the right invocation.
_fzf=$(command -v fzf 2>/dev/null)
if [ -z "$_fzf" ]; then
    _fd=$(configsys location fzf 2>/dev/null)
    [ -n "$_fd" ] && _fzf=$(ls -1 "$_fd"/fzf 2>/dev/null | tail -1)
    [ -x "$_fzf" ] && alias fzf="$_fzf"
    unset _fd
fi
if [ -x "$_fzf" ]; then
    _fzf_ver=$("$_fzf" --version 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+')
    if [ "${_fzf_ver%%.*}" -gt 0 ] 2>/dev/null || [ "${_fzf_ver#*.}" -ge 48 ] 2>/dev/null; then
        eval "$("$_fzf" --zsh)"                         # fzf >= 0.48: one-shot unified integration
    else
        for _kb in /usr/share/doc/fzf/examples/key-bindings.zsh \
                   /usr/share/fzf/key-bindings.zsh /usr/share/fzf/shell/key-bindings.zsh; do
            [ -r "$_kb" ] && { source "$_kb"; break; }
        done
        for _cp in /usr/share/doc/fzf/examples/completion.zsh \
                   /usr/share/fzf/completion.zsh /usr/share/fzf/shell/completion.zsh; do
            [ -r "$_cp" ] && { source "$_cp"; break; }
        done
        unset _kb _cp
    fi
    unset _fzf_ver
fi
unset _fzf
