# Bun: tarball dir (bun-linux-*/) + BUN_INSTALL global bin on PATH.
let bun_loc = (cs-loc bun)
if ($bun_loc != "") { cs-prepend (cs-glob1 $"($bun_loc)/bun-linux-*") }
$env.BUN_INSTALL = $"($env.HOME)/.bun"
cs-append $"($env.HOME)/.bun/bin"
