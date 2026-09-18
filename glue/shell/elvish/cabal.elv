# cabal: put its user-install bin dir(s) on PATH.
use path
if (and (path:is-dir $E:HOME/.cabal/bin) (not (has-value $paths $E:HOME/.cabal/bin))) {
  set paths = [$@paths $E:HOME/.cabal/bin]
}
if (and (path:is-dir $E:HOME/.local/bin) (not (has-value $paths $E:HOME/.local/bin))) {
  set paths = [$@paths $E:HOME/.local/bin]
}
