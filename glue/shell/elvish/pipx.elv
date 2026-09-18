# pipx: put its user-install bin dir(s) on PATH.
use path
if (and (path:is-dir $E:HOME/.local/bin) (not (has-value $paths $E:HOME/.local/bin))) {
  set paths = [$E:HOME/.local/bin $@paths]
}
