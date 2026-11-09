# Nim: put the tarball-installed compiler's bin on PATH (no-op where native); nimble installs
# package binaries to ~/.nimble/bin.
set -l loc (cs_loc nim)
test -n "$loc"; and test -x "$loc/bin/nim"; and fish_add_path -g "$loc/bin"
test -d "$HOME/.nimble/bin"; and fish_add_path -gaP "$HOME/.nimble/bin"
