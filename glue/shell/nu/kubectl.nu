# kubectl: put the configsys-managed dir on PATH. No-op where native on PATH.
let kubectl_loc = (cs-loc kubectl)
if (($kubectl_loc != "") and ($"($kubectl_loc)/kubectl" | path exists)) { cs-append $kubectl_loc }
