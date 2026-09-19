# SDKMAN — put `sdk`'s selected JVM toolchains (java/scala/groovy/sbt/…) on PATH. sdkman-init.sh
# prepends each candidate's `current/bin`; the bash bridge imports that + SDKMAN_DIR. The `sdk`
# FUNCTION itself doesn't cross to nu (it's a bash function) — install/switch SDKs from bash; the
# selected binaries are then usable in nu. No-op if SDKMAN isn't installed.
cs-bash-env 'export SDKMAN_DIR="$HOME/.sdkman"; [ -s "$SDKMAN_DIR/bin/sdkman-init.sh" ] && source "$SDKMAN_DIR/bin/sdkman-init.sh"'
