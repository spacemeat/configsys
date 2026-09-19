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
# The managed install locations, cached. A `configsys location <x>` per snippet is ~250ms (a whole
# Python startup); even one `--all` call per launch is ~250ms. So configsys writes a `<comp>\t<path>`
# cache file (glue-locations.tsv, refreshed by `location --all`, invalidated on a pin/pick edit); a
# normal launch reads it (~1ms, freshness via `find -mmin -60`). Only on a cold/stale cache do we spawn
# `configsys location --all` (which rewrites it). cs-loc then reads this map. `?()` swallows a failing
# configsys so a hiccup leaves the cache empty, not a broken block.
fn -cs-state-dir {
  if (has-env CONFIGSYS_STATE_DIR) { put $E:CONFIGSYS_STATE_DIR
  } elif (has-env XDG_CONFIG_HOME) { put $E:XDG_CONFIG_HOME/configsys
  } else { put $E:HOME/.config/configsys }
}
var cs-locs = [&]
fn -cs-load-locs {
  var cache = (-cs-state-dir)/glue-locations.tsv
  var raw = ''
  if (and (path:is-regular $cache) (not-eq (find $cache -mmin -60 2>/dev/null | slurp) '')) {
    set raw = (slurp < $cache)
  } else {
    set raw = (configsys location --all 2>/dev/null | slurp)
  }
  for _line [(str:split "\n" $raw)] {
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
