# uv: tarball dir (never-auto binding) + `uv tool` bin (~/.local/bin).
let uv_loc = (cs-loc uv)
if ($uv_loc != "") {
  let d = (cs-glob1 $"($uv_loc)/uv-*")
  if ($d != "") { cs-prepend $d } else if ($"($uv_loc)/uv" | path exists) { cs-prepend $uv_loc }
}
cs-prepend $"($env.HOME)/.local/bin"
