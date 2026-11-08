# Homebrew: its bin/sbin APPENDED to PATH (so a formula fills gaps, never shadows a system tool — the
# installer's `brew shellenv` prepends) + the HOMEBREW_* vars. Shared prefix first, then ~/.linuxbrew.
use path
for hb [/home/linuxbrew/.linuxbrew $E:HOME/.linuxbrew] {
  if (path:is-regular &follow-symlink $hb/bin/brew) {
    set E:HOMEBREW_PREFIX = $hb
    set E:HOMEBREW_CELLAR = $hb/Cellar
    set E:HOMEBREW_REPOSITORY = $hb/Homebrew
    if (not (has-value $paths $hb/bin)) { set paths = [$@paths $hb/bin $hb/sbin] }
    break
  }
}
