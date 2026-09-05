# Deno: tarball install dir (no-op when native) + `deno install` global scripts.
set -l loc (configsys location deno 2>/dev/null)
test -n "$loc"; and test -x "$loc/deno"; and fish_add_path -g "$loc"
test -d "$HOME/.deno/bin"; and fish_add_path -ga "$HOME/.deno/bin"
