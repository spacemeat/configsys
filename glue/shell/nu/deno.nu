# Deno: tarball dir (no-op when native) + `deno install` global scripts.
let deno_loc = (cs-loc deno)
if (($deno_loc != "") and ($"($deno_loc)/deno" | path exists)) { cs-prepend $deno_loc }
cs-append $"($env.HOME)/.deno/bin"
