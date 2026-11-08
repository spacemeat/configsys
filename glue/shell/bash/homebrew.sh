# Homebrew: its bin/sbin APPENDED to PATH (so a formula fills gaps, never shadows a system tool — the
# installer's `brew shellenv` prepends) + the HOMEBREW_* vars. Shared prefix first, then ~/.linuxbrew.
for _hb in /home/linuxbrew/.linuxbrew "$HOME/.linuxbrew"; do
    if [ -x "$_hb/bin/brew" ]; then
        export HOMEBREW_PREFIX="$_hb" HOMEBREW_CELLAR="$_hb/Cellar" HOMEBREW_REPOSITORY="$_hb/Homebrew"
        case ":$PATH:" in *":$_hb/bin:"*) ;; *) export PATH="$PATH:$_hb/bin:$_hb/sbin" ;; esac
        break
    fi
done
unset _hb
