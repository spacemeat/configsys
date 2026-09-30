# arduino: alias to the appImage/binary wherever configsys installed it. No-ops where native.
set -l loc (cs_loc arduino)
test -x "$loc"; and alias arduino "$loc"
