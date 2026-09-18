# fd — Debian/Ubuntu ship the binary as `fdfind`. Alias it back to `fd` when only fdfind is present.
if (and (has-external fdfind) (not (has-external fd))) {
  edit:add-var fd~ {|@a| fdfind $@a }
}
