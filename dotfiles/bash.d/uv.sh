# uv: tarball install dir (never-auto binding; no-op for the pipx/native default) + `uv tool` bin.
_uv=$(configsys location uv 2>/dev/null)
if [ -n "$_uv" ]; then
    _ub=$(ls -d "$_uv"/uv-*/ 2>/dev/null | tail -1)
    if [ -n "$_ub" ]; then export PATH="$_ub:$PATH"; elif [ -x "$_uv/uv" ]; then export PATH="$_uv:$PATH"; fi
    unset _ub
fi
unset _uv
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
