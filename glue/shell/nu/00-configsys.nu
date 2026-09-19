# Make `configsys` callable from later glue snippets and interactively. Defined at TOP LEVEL (a `def`
# inside an `if` would be scoped to that block and never reach the REPL — same trap as elvish's
# fn-in-if). The check for a real `configsys` on PATH lives INSIDE the command. Falls back to the
# clone launcher at $HOME/<src>/configsys/configsys.sh (override with $CONFIGSYS_LAUNCHER; <src>
# defaults to `src`, or $CONFIGSYS_SRC_DIR). `which --all ... where type == external` finds a real
# binary (never this def itself).
def --wrapped configsys [...args] {
  if (which --all configsys | where type == "external" | is-not-empty) {
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

# configsys's state dir (for the glue-locations cache) — mirrors paths.py: CONFIGSYS_STATE_DIR, else
# $XDG_CONFIG_HOME/configsys, else ~/.config/configsys.
def cs-state-dir [] {
  if ($env.CONFIGSYS_STATE_DIR? | is-not-empty) { $env.CONFIGSYS_STATE_DIR
  } else { ($env.XDG_CONFIG_HOME? | default $"($env.HOME)/.config") | path join configsys }
}

# The managed install locations, cached. A `configsys location <x>` per snippet is ~250ms (a whole
# Python startup); even one `--all` call per shell launch is ~250ms. So configsys writes a
# `<comp>\t<path>` cache file (glue-locations.tsv, refreshed by `location --all` and invalidated on a
# pin/pick edit); a normal launch reads that file (~1ms). Only on a cold/stale (>1h) cache do we spawn
# `configsys location --all` (which rewrites it). cs-loc then reads this record — instant.
$env.__cs_locs = (do {
  let cache = (cs-state-dir | path join glue-locations.tsv)
  let fresh = (($cache | path exists) and (try { ((date now) - (ls $cache | get modified | first)) < 1hr } catch { false }))
  let raw = (if $fresh { (open --raw $cache) } else {
    (do --ignore-errors { configsys location --all | complete } | if (($in != null) and ($in.exit_code == 0)) { $in.stdout } else { "" })
  })
  ($raw | lines | where {|l| $l != ""}
    | split column (char tab) name path
    | reduce --fold {} {|row, acc| $acc | upsert $row.name ($row.path | default "" | str trim) })
})

# cs-loc <name>: the managed install location of a component ("" if none / a native install). An
# instant lookup into the $env.__cs_locs cache above. Used by the tarball/appImage snippets to find
# their off-PATH binaries.
def cs-loc [name: string] { ($env.__cs_locs? | default {} | get --optional $name | default "") }

# cf: shorthand for configsys.
def --wrapped cf [...args] { configsys ...$args }

# cs-prepend / cs-append <dir>: add a dir to the FRONT / BACK of PATH when it exists, deduped. `--env`
# so the mutation reaches the caller (config.nu's top scope -> the REPL). The PATH glue snippets use
# these instead of repeating the `$env.PATH = ($env.PATH | … | uniq)` dance.
def --env cs-prepend [d: string] { if (($d != "") and ($d | path exists)) { $env.PATH = ($env.PATH | prepend $d | uniq) } }
def --env cs-append  [d: string] { if (($d != "") and ($d | path exists)) { $env.PATH = ($env.PATH | append  $d | uniq) } }

# cs-glob1 <pattern>: the first existing path matching a glob (dirs and files), or "". Empty-safe.
def cs-glob1 [pattern: string] { (glob $pattern | get 0? | default "") }

# cs-bash-delta <bash-command>: run a bash command (source a setup script / eval a tool's init) and
# return the environment DELTA it produced vs nu's current env — { vars: {NAME: VAL …}, path: [dir …] }
# (new PATH dirs, changed non-PATH vars; shell-internal noise skipped). Values are single-line
# (env-setup scripts don't export multiline); a value keeping its own `=` survives (parse is
# non-greedy on the name). A failed bash run yields an empty delta.
def cs-bash-delta [cmd: string] {
  let r = (^bash -c $'{ ($cmd) ; } >/dev/null 2>&1; env' | complete)
  if $r.exit_code != 0 { return { vars: {}, path: [] } }
  let ignore = ["_" "SHLVL" "PWD" "OLDPWD" "SHELL" "PS1" "PS2" "BASHOPTS"
                "BASH_EXECUTION_STRING" "BASH_VERSION" "BASH_VERSINFO" "BASHPID"]
  let cur = $env.PATH
  mut vars = {}
  mut pathadd = []
  for kv in ($r.stdout | lines | where {|x| ($x | str contains "=")}) {
    let m = ($kv | parse "{name}={value}")
    if ($m | is-empty) { continue }
    let p = ($m | first)
    if (($p.name in $ignore) or ($p.name == "")) { continue }
    if $p.name == "PATH" {
      $pathadd = ($p.value | split row (char esep) | where {|d| ($d != "") and ($d not-in $cur) })
    } else if (($env | get --optional $p.name) != $p.value) {
      $vars = ($vars | upsert $p.name $p.value)
    }
  }
  { vars: $vars, path: $pathadd }
}

# cs-bash-env <bash-command>: nushell's `bass` — import a bash env-setup script's PATH/env into $env.
# For tools that ship only a bash env script (sdkman/vulkan-sdk/gnustep/miniforge) or whose init emits
# bash (pyenv/opam/luarocks). MEMOIZED: the computed delta is cached under the state dir keyed by the
# command (each ~250ms — a bash spawn + env capture + parse), so a normal launch applies a cached delta
# (~ms) instead of re-running bash. Cache is fresh for 1h (the PATH dirs it adds are stable even across
# `sdk use`, which only re-points a symlink). Caveat: bash FUNCTIONS (sdk/conda/pyenv) don't cross to
# nu — only the PATH/env does. `--env` so it persists; self-guards (a failed bash run imports nothing).
def --env cs-bash-env [cmd: string] {
  let cache = (cs-state-dir | path join nu-bash-env $"(($cmd | hash md5)).nuon")
  let fresh = (($cache | path exists) and (try { ((date now) - (ls $cache | get modified | first)) < 1hr } catch { false }))
  let delta = (if $fresh { (try { open $cache } catch { cs-bash-delta $cmd }) } else {
    let computed = (cs-bash-delta $cmd)
    try { mkdir ($cache | path dirname); $computed | save --force $cache }
    $computed
  })
  for kv in ($delta.vars | transpose name value) { load-env { ($kv.name): $kv.value } }
  for d in $delta.path { cs-prepend $d }
}
