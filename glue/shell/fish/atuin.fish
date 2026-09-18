# atuin — magical shell history (SQLite-backed, searchable, optional sync). Binds Ctrl-R / Up to
# atuin's search UI on shell start. No-op until atuin is installed.
command -v atuin >/dev/null 2>&1; and atuin init fish | source
