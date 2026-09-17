# Make `configsys` callable from Elvish conf.d snippets (so later snippets can call it). Prefer a
# real `configsys` on PATH (e.g. a pipx install); else fall back to the clone launcher at
# $E:HOME/<src>/configsys/configsys.sh (override with $E:CONFIGSYS_LAUNCHER; <src> defaults to
# `src`, or $E:CONFIGSYS_SRC_DIR). This runs first (00- prefix) so its helper is available to the rest.
use path

if (not (has-external configsys)) {
  fn configsys {|@a|
    var src = 'src'
    if (has-env CONFIGSYS_SRC_DIR) { set src = $E:CONFIGSYS_SRC_DIR }
    var launcher = $E:HOME/$src/configsys/configsys.sh
    if (has-env CONFIGSYS_LAUNCHER) { set launcher = $E:CONFIGSYS_LAUNCHER }
    if (path:is-regular $launcher) {
      (external $launcher) $@a
    } else {
      echo "configsys: launcher not found — set CONFIGSYS_LAUNCHER, or install configsys on your PATH" >&2
    }
  }
}

# `cf` shorthand (an Elvish edit-mode abbreviation would be interactive-only; a fn works everywhere).
fn cf {|@a| configsys $@a }
