# Make `configsys` callable from later glue snippets and interactively. Defined at TOP LEVEL (an
# `fn` inside an `if` would be local to that block) — the check for a real `configsys` on PATH lives
# INSIDE the function instead. Falls back to the clone launcher at $E:HOME/<src>/configsys/configsys.sh
# (override with $E:CONFIGSYS_LAUNCHER; <src> defaults to `src`, or $E:CONFIGSYS_SRC_DIR).
use path
use str
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
# Fetch EVERY managed install location in ONE call and cache it. A `configsys location <x>` per
# snippet is ~250ms (a whole Python startup); dozens would add seconds to elvish startup. `--all`
# prints `<comp>\t<path>` for the whole requested set in one process; cs-loc then reads this map —
# instant. `?()` swallows a failing configsys so a hiccup leaves the cache empty, not a broken block.
var cs-locs = [&]
fn -cs-load-locs {
  for _line [(configsys location --all 2>/dev/null)] {
    var parts = [(str:split "\t" $_line)]
    if (== (count $parts) 2) { set cs-locs[$parts[0]] = $parts[1] }
  }
}
nop ?(-cs-load-locs)

# cs-loc <name>: the managed install location of a component (or "" if none/native). An instant
# lookup into the cs-locs cache above. Used by the tarball/appImage glue snippets to find their
# off-PATH binaries.
fn cs-loc {|name|
  if (has-key $cs-locs $name) { put $cs-locs[$name] } else { put '' }
}

fn cf {|@a| configsys $@a }
