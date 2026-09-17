# Lean 4 via elan (userland version manager): elan installs `lean`/`lake` under ~/.elan. Put its
# bin on PATH so they resolve without a login-shell rc edit. No-op until elan/lean is installed.
[ -d "$HOME/.elan/bin" ] && export PATH="$HOME/.elan/bin:$PATH"
