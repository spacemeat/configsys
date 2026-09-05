# unityhub: alias to the appImage/binary wherever configsys installed it. No-ops where native.
set -l loc (configsys location unityhub 2>/dev/null)
test -x "$loc"; and alias unityhub "$loc"
