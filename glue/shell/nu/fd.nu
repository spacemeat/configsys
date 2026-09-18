# fd — Debian/Ubuntu ship the binary as `fdfind`. Expose it as `fd` when a real `fd` isn't on PATH.
# A conditional `def` can't be defined inside an `if` (parse-time scoping keeps it block-local, so it
# never reaches the REPL — same reason elvish uses edit:add-var), so the command is defined
# unconditionally and self-guards at runtime: it resolves a real external `fd` (never itself), else
# falls back to fdfind.
def --wrapped fd [...rest] {
  let real = (which --all fd | where type == external | get path)
  if ($real | is-not-empty) { ^($real | first) ...$rest } else { ^fdfind ...$rest }
}
