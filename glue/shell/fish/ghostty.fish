# ghostty: alias to the appImage/binary wherever configsys installed it. No-ops where native.
set -l loc (cs_loc ghostty)
test -x "$loc"; and alias ghostty "$loc"
