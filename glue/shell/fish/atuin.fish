# atuin — magical shell history (SQLite-backed, searchable, optional sync). Binds Ctrl-R / Up to
# atuin's search UI on shell start (interactive shells only — a `fish -c` has no prompt to bind). No-op
# until atuin is installed.
status is-interactive; and command -v atuin >/dev/null 2>&1; and atuin init fish | source
