# Homebrew: its bin/sbin APPENDED to PATH (so a formula fills gaps, never shadows a system tool — the
# installer's `brew shellenv` prepends) + the HOMEBREW_* vars. Shared prefix first, then ~/.linuxbrew.
# $env.PATH is a list in nushell; `uniq` keeps the entries from piling up on re-source.
let hb = ([/home/linuxbrew/.linuxbrew $"($env.HOME)/.linuxbrew"] | where {|p| $"($p)/bin/brew" | path exists } | get 0?)
if $hb != null {
  $env.HOMEBREW_PREFIX = $hb
  $env.HOMEBREW_CELLAR = $"($hb)/Cellar"
  $env.HOMEBREW_REPOSITORY = $"($hb)/Homebrew"
  $env.PATH = ($env.PATH | append [$"($hb)/bin" $"($hb)/sbin"] | uniq)
}
