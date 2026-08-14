# SDKMAN — put `sdk` and the current-selected JVM SDKs (java/scala/groovy/sbt/leiningen/…) on PATH.
# sdkman-init.sh defines the `sdk` shell function AND prepends each candidate's `current` bin to
# PATH, so a `sdk install`ed toolchain is usable in new shells. No-op if SDKMAN isn't installed.
export SDKMAN_DIR="$HOME/.sdkman"
[ -s "$SDKMAN_DIR/bin/sdkman-init.sh" ] && source "$SDKMAN_DIR/bin/sdkman-init.sh"
