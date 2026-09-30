# elvish: put the tarball-installed elvish on PATH so `elvish` execs and is detected. No-op where native.
set -l loc (cs_loc elvish)
test -n "$loc"; and test -x "$loc/elvish"; and fish_add_path -gp "$loc"
