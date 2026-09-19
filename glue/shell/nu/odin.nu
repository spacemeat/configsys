# Odin: tarball dir (root or versioned subdir; no-op when native).
let odin_loc = (cs-loc odin)
if ($odin_loc != "") {
  let d = (cs-glob1 $"($odin_loc)/odin-linux-*")
  if ($d != "") { cs-prepend $d } else if ($"($odin_loc)/odin" | path exists) { cs-prepend $odin_loc }
}
