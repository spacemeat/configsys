# fd — Debian/Ubuntu ship the binary as `fdfind` (the `fd` name collides with fdclone).
# Alias it back to `fd` when only fdfind is present.
command -v fdfind >/dev/null 2>&1 && ! command -v fd >/dev/null 2>&1 && alias fd=fdfind
