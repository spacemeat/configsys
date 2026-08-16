# kubectl: where configsys installs the static binary off-PATH (tarball), add it to PATH and
# enable completion. No-ops where kubectl is native (arch/atomic) already on PATH.
_kc=$(configsys location kubectl 2>/dev/null)
[ -n "$_kc" ] && [ -x "$_kc/kubectl" ] && export PATH="$PATH:$_kc"
unset _kc
command -v kubectl >/dev/null 2>&1 && source <(kubectl completion bash) 2>/dev/null
