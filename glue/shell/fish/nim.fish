# Nim: nimble installs package binaries to ~/.nimble/bin.
test -d "$HOME/.nimble/bin"; and fish_add_path -ga "$HOME/.nimble/bin"
