# SDKMAN — import sdkman-init.sh's env (the selected candidates' current/bin on PATH) via bass; SDKMAN
# ships no fish init, and the `sdk` function itself stays bash-only. No-op without bass/SDKMAN.
set -gx SDKMAN_DIR "$HOME/.sdkman"
if type -q bass; and test -s "$SDKMAN_DIR/bin/sdkman-init.sh"
    bass source "$SDKMAN_DIR/bin/sdkman-init.sh"
end
