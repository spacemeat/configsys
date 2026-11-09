# Nim: nimble installs package binaries to ~/.nimble/bin.
test -d "$HOME/.nimble/bin"; and fish_add_path -gaP "$HOME/.nimble/bin"
