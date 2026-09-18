# Bun: tarball dir (bun-linux-*/) + BUN_INSTALL global bin on PATH.
use path
var loc = (cs-loc bun)
if (not-eq $loc '') {
  for d [$loc/bun-linux-*[nomatch-ok]] { if (and (path:is-dir $d) (not (has-value $paths $d))) { set paths = [$d $@paths]; break } }
}
set-env BUN_INSTALL $E:HOME/.bun
if (and (path:is-dir $E:HOME/.bun/bin) (not (has-value $paths $E:HOME/.bun/bin))) { set paths = [$@paths $E:HOME/.bun/bin] }
