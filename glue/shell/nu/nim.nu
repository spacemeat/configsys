# nim: put the tarball compiler's bin (no-op where native) and its user-install bin dir on PATH.
let nim_loc = (cs-loc nim)
if ($nim_loc != "") { cs-prepend $"($nim_loc)/bin" }
cs-append $"($env.HOME)/.nimble/bin"
