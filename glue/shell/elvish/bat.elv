# bat — Debian/Ubuntu ship the binary as `batcat`. Alias it back to `bat` when only batcat is present.
# `edit:add-var name~` injects into the interactive namespace (a plain `fn` inside `if` wouldn't persist).
if (and (has-external batcat) (not (has-external bat))) {
  edit:add-var bat~ {|@a| batcat $@a }
}
