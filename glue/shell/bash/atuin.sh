# atuin — magical shell history (SQLite-backed, searchable, optional sync). Binds Ctrl-R (and the
# Up arrow) to atuin's search UI on shell start. No-op until atuin is installed.
if command -v atuin >/dev/null 2>&1; then
    eval "$(atuin init bash)"
fi
