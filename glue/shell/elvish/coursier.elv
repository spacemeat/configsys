# coursier: put its user-install bin dir(s) on PATH.
use path
if (and (path:is-dir $E:HOME/.local/share/coursier/bin) (not (has-value $paths $E:HOME/.local/share/coursier/bin))) {
  set paths = [$@paths $E:HOME/.local/share/coursier/bin]
}
