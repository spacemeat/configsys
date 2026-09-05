# pipx: global CLIs install to ~/.local/bin.
test -d "$HOME/.local/bin"; and fish_add_path -g "$HOME/.local/bin"
