# Make `configsys` callable from later glue snippets and interactively. Defined at TOP LEVEL (an
# `fn` inside an `if` would be local to that block) — the check for a real `configsys` on PATH lives
# INSIDE the function instead. Falls back to the clone launcher at $E:HOME/<src>/configsys/configsys.sh
# (override with $E:CONFIGSYS_LAUNCHER; <src> defaults to `src`, or $E:CONFIGSYS_SRC_DIR).
use path
fn configsys {|@a|
  if (has-external configsys) {
    (external configsys) $@a
  } else {
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
# cs-loc <name>: the managed install location of a component (or "" if none/native). Wraps
# `configsys location` (exits 0 with empty output when unmanaged), empty-safe. Used by the
# tarball/appImage glue snippets to find their off-PATH binaries.
fn cs-loc {|name|
  var loc = ''
  for _l [(configsys location $name 2>/dev/null)] { set loc = $_l }
  put $loc
}

fn cf {|@a| configsys $@a }
