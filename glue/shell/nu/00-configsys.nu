# Make `configsys` callable from later glue snippets and interactively. Defined at TOP LEVEL (a `def`
# inside an `if` would be scoped to that block and never reach the REPL — same trap as elvish's
# fn-in-if). The check for a real `configsys` on PATH lives INSIDE the command. Falls back to the
# clone launcher at $HOME/<src>/configsys/configsys.sh (override with $CONFIGSYS_LAUNCHER; <src>
# defaults to `src`, or $CONFIGSYS_SRC_DIR). `which --all ... where type == external` finds a real
# binary (never this def itself).
def --wrapped configsys [...args] {
  if (which --all configsys | where type == external | is-not-empty) {
    ^configsys ...$args
  } else {
    let src = ($env.CONFIGSYS_SRC_DIR? | default "src")
    let launcher = ($env.CONFIGSYS_LAUNCHER? | default $"($env.HOME)/($src)/configsys/configsys.sh")
    if ($launcher | path exists) {
      ^$launcher ...$args
    } else {
      print -e "configsys: launcher not found — set CONFIGSYS_LAUNCHER, or install configsys on your PATH"
    }
  }
}

# cs-loc <name>: the managed install location of a component ("" if none / a native install). Wraps
# `configsys location` (which exits 0 with empty output when unmanaged); `do --ignore-errors` swallows
# a hard failure so a snippet can't abort the rest of the block. Used by the tarball/appImage snippets
# to find their off-PATH binaries.
def cs-loc [name: string] {
  (do --ignore-errors { configsys location $name } | default "" | str trim)
}

# cf: shorthand for configsys.
def --wrapped cf [...args] { configsys ...$args }
