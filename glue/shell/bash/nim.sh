# Nim: put the tarball-installed compiler's bin (nim, nimble) on PATH — strip: 1 lands it in
# <loc>/bin; a no-op where nim is native — and nimble's package binaries (~/.nimble/bin).
_n=$(cs_loc nim)
[ -n "$_n" ] && [ -x "$_n/bin/nim" ] && case ":$PATH:" in *":$_n/bin:"*) ;; *) export PATH="$_n/bin:$PATH" ;; esac
unset _n
[ -d "$HOME/.nimble/bin" ] && export PATH="$PATH:$HOME/.nimble/bin"
