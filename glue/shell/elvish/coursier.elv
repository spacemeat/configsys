# coursier: put its apps bin dir (populated by `cs install`; $COURSIER_BIN_DIR overrides) on PATH.
use path
var csbin = $E:HOME/.local/share/coursier/bin
if (and (has-env COURSIER_BIN_DIR) (not-eq $E:COURSIER_BIN_DIR '')) { set csbin = $E:COURSIER_BIN_DIR }
if (and (path:is-dir $csbin) (not (has-value $paths $csbin))) {
  set paths = [$@paths $csbin]
}
