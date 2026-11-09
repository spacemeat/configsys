# coursier: put its apps bin dir (populated by `cs install`; $COURSIER_BIN_DIR overrides) on PATH.
cs-append (if ($env.COURSIER_BIN_DIR? | is-not-empty) { $env.COURSIER_BIN_DIR } else { $"($env.HOME)/.local/share/coursier/bin" })
