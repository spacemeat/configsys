# bat — Debian/Ubuntu ship the binary as `batcat`. Expose it as `bat` when a real bat isn't on PATH.
def --wrapped bat [...rest] {
  let real = (which --all bat | where type == "external" | get path)
  if ($real | is-not-empty) { ^($real | first) ...$rest } else { ^batcat ...$rest }
}
