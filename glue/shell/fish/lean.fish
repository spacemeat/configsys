# Lean 4 via elan (userland version manager): put ~/.elan/bin on PATH so lean/lake resolve.
test -d "$HOME/.elan/bin"; and fish_add_path -gp "$HOME/.elan/bin"
