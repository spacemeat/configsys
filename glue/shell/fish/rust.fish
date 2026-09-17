# Rust: rustup toolchain + `cargo install` binaries live in ~/.cargo/bin.
test -d "$HOME/.cargo/bin"; and fish_add_path -g "$HOME/.cargo/bin"
