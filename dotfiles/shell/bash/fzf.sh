# fzf: resolve the binary (native on PATH, else the tarball under the managed dir), then load its
# bash integration. The unified `fzf --bash` needs fzf >= 0.48; older fzf (e.g. Ubuntu/Pop 22.04's
# 0.29) has no `--bash` and instead ships SEPARATE key-bindings + completion scripts — so check the
# version and pick the right invocation instead of blindly passing --bash (which fails on old fzf,
# leaving no bindings at all).
_fzf=$(command -v fzf 2>/dev/null)
if [ -z "$_fzf" ]; then
    _fd=$(configsys location fzf 2>/dev/null)
    [ -n "$_fd" ] && _fzf=$(ls -1 "$_fd"/fzf 2>/dev/null | tail -1)
    [ -x "$_fzf" ] && alias fzf="$_fzf"
    unset _fd
fi
if [ -x "$_fzf" ]; then
    # "0.29 (devel)" / "0.48.1 (brew)" -> the leading MAJOR.MINOR
    _fzf_ver=$("$_fzf" --version 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+')
    if [ "${_fzf_ver%%.*}" -gt 0 ] 2>/dev/null || [ "${_fzf_ver#*.}" -ge 48 ] 2>/dev/null; then
        eval "$("$_fzf" --bash)"                        # fzf >= 0.48: one-shot unified integration
    else
        # pre-0.48: source key-bindings (Ctrl-R / Ctrl-T / Alt-C) + completion from the usual spots
        for _kb in /usr/share/doc/fzf/examples/key-bindings.bash \
                   /usr/share/fzf/key-bindings.bash /usr/share/fzf/shell/key-bindings.bash; do
            [ -r "$_kb" ] && { . "$_kb"; break; }
        done
        for _cp in /usr/share/doc/fzf/examples/completion.bash \
                   /usr/share/fzf/completion.bash /usr/share/fzf/shell/completion.bash \
                   /usr/share/bash-completion/completions/fzf; do
            [ -r "$_cp" ] && { . "$_cp"; break; }
        done
        unset _kb _cp
    fi
    unset _fzf_ver
fi
unset _fzf
