# gleam: add the tarball-installed gleam (single static binary) to PATH. No-op where gleam is
# native (pacman/apk/brew) and already on PATH.
_gl=$(cs_loc gleam)
[ -n "$_gl" ] && [ -x "$_gl/gleam" ] && case ":$PATH:" in *":$_gl:"*) ;; *) PATH="$PATH:$_gl"; export PATH ;; esac
unset _gl
