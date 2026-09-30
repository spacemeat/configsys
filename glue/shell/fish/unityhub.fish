# unityhub: alias to the appImage/binary wherever configsys installed it. No-ops where native.
set -l loc (cs_loc unityhub)
test -x "$loc"; and alias unityhub "$loc"
