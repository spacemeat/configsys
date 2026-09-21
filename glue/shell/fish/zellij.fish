# zellij: alias to the tarball-installed binary (flat at the install root). No-ops where native.
set -l loc (configsys location zellij 2>/dev/null)
if test -n "$loc"; and test -x "$loc/zellij"
    alias zellij "$loc/zellij"
end
