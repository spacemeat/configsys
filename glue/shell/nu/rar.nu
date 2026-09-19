# rar: put the configsys-managed dir on PATH. No-op where native on PATH.
let rar_loc = (cs-loc rar)
if (($rar_loc != "") and ($"($rar_loc)/rar/rar" | path exists)) { cs-prepend $"($rar_loc)/rar" }
