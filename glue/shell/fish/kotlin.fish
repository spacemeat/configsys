# kotlin: add the tarball-installed Kotlin compiler's bin to PATH (kotlinc/bin). No-op where native.
set -l loc (cs_loc kotlin)
test -n "$loc"; and test -d "$loc/kotlinc/bin"; and fish_add_path -g "$loc/kotlinc/bin"
