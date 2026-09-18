# rust: put its user-install bin dir(s) on PATH.
use path
if (and (path:is-dir $E:HOME/.cargo/bin) (not (has-value $paths $E:HOME/.cargo/bin))) {
  set paths = [$E:HOME/.cargo/bin $@paths]
}
