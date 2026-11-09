# Homebrew: its bin/sbin APPENDED to PATH (so a formula fills gaps, never shadows a system tool — the
# installer's `brew shellenv` prepends) + the HOMEBREW_* vars. Shared prefix first, then ~/.linuxbrew.
for hb in /home/linuxbrew/.linuxbrew $HOME/.linuxbrew
    if test -x $hb/bin/brew
        set -gx HOMEBREW_PREFIX $hb
        set -gx HOMEBREW_CELLAR $hb/Cellar
        set -gx HOMEBREW_REPOSITORY $hb/Homebrew
        fish_add_path -gaP $hb/bin $hb/sbin
        break
    end
end
