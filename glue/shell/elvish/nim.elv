# nim: put its user-install bin dir(s) on PATH.
use path
if (and (path:is-dir $E:HOME/.nimble/bin) (not (has-value $paths $E:HOME/.nimble/bin))) {
  set paths = [$@paths $E:HOME/.nimble/bin]
}
