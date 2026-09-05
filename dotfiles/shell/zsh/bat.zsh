# bat — Debian/Ubuntu ship the binary as `batcat` (the `bat` name collides with bacula-console).
# Alias it back to `bat` when only batcat is present.
if command -v batcat >/dev/null 2>&1 && ! command -v bat >/dev/null 2>&1; then
    alias bat=batcat
fi
