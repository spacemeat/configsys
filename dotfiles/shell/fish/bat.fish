# bat — Debian/Ubuntu ship the binary as `batcat`. Alias it back to `bat` when only batcat is present.
if command -v batcat >/dev/null 2>&1; and not command -v bat >/dev/null 2>&1
    alias bat batcat
end
