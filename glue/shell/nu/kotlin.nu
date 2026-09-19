# kotlin: put the tarball compiler's bin (kotlinc/bin) on PATH. No-op where native.
let kotlin_loc = (cs-loc kotlin)
if ($kotlin_loc != "") { cs-append $"($kotlin_loc)/kotlinc/bin" }
