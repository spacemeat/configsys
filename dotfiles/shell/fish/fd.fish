# fd — Debian/Ubuntu ship the binary as `fdfind`. Alias it back to `fd` when only fdfind is present.
if command -v fdfind >/dev/null 2>&1; and not command -v fd >/dev/null 2>&1
    alias fd fdfind
end
