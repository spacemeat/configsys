# Rust: rustup toolchain + `cargo install` binaries live in ~/.cargo/bin (rustup is run
# --no-modify-path, so nothing else puts it on PATH).
[ -d "$HOME/.cargo/bin" ] && case ":$PATH:" in
    *":$HOME/.cargo/bin:"*) ;; *) export PATH="$HOME/.cargo/bin:$PATH" ;;
esac
