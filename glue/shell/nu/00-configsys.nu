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

# Fetch EVERY managed install location in ONE call and cache it. A `configsys location <x>` per snippet
# is ~250ms (a whole Python startup); dozens of them would add seconds to every nu launch. `--all`
# prints `<comp>\t<path>` for the whole requested set in one process; cs-loc then reads this record —
# instant. `complete` captures streams (the per-component stderr advisories don't leak); the fallbacks
# keep a missing/blank/failed configsys from breaking config.nu.
$env.__cs_locs = (do --ignore-errors { configsys location --all | complete }
  | if (($in != null) and ($in.exit_code == 0)) {
      ($in.stdout | lines | where {|l| $l != ""}
        | split column (char tab) name path
        | reduce --fold {} {|row, acc| $acc | upsert $row.name ($row.path | default "" | str trim) })
    } else { {} })

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

# cs-bash-env <bash-command>: nushell's `bass` — run a bash command (typically sourcing an env-setup
# script, or eval-ing a tool's init) and import the environment CHANGES it produces into $env. PATH
# becomes a deduped list; shell-internal vars and values that didn't change are skipped. For tools
# that ship only a bash env script (sdkman/vulkan-sdk/gnustep/miniforge) or whose init emits bash
# (pyenv/opam/luarocks). Caveat: the bash FUNCTIONS such a script defines (sdk/conda/pyenv) don't
# cross to nu — but the PATH/env it sets do, so installed toolchains are usable. `--env` so the import
# persists; self-guards (a failed bash run imports nothing). Values are single-line (env-setup scripts
# don't export multiline values); a value keeping its own `=` survives (parse is non-greedy on name).
def --env cs-bash-env [cmd: string] {
  let r = (^bash -c $'{ ($cmd) ; } >/dev/null 2>&1; env' | complete)
  if $r.exit_code != 0 { return }
  let ignore = ["_" "SHLVL" "PWD" "OLDPWD" "SHELL" "PS1" "PS2" "BASHOPTS"
                "BASH_EXECUTION_STRING" "BASH_VERSION" "BASH_VERSINFO" "BASHPID"]
  for kv in ($r.stdout | lines | where {|x| ($x | str contains "=")}) {
    let m = ($kv | parse "{name}={value}")
    if ($m | is-empty) { continue }
    let p = ($m | first)
    if (($p.name in $ignore) or ($p.name == "")) { continue }
    if $p.name == "PATH" {
      $env.PATH = ($p.value | split row (char esep) | where {|x| $x != ""} | uniq)
    } else if (($env | get --optional $p.name) != $p.value) {
      load-env { ($p.name): $p.value }
    }
  }
}
