# v: put the configsys-managed dir on PATH. No-op where native on PATH.
let v_loc = (cs-loc v)
if (($v_loc != "") and ($"($v_loc)/v/v" | path exists)) { cs-prepend $"($v_loc)/v" }
