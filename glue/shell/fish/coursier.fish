# coursier: add the coursier apps bin (populated by `cs install`) to PATH.
set -l cs "$HOME/.local/share/coursier/bin"
test -n "$COURSIER_BIN_DIR"; and set cs "$COURSIER_BIN_DIR"
test -d "$cs"; and fish_add_path -ga "$cs"
