# signal-cli: prepend the tarball install dir to PATH. No-op where native on PATH.
let sc_loc = (cs-loc signal-cli)
if (($sc_loc != "") and ($"($sc_loc)/signal-cli" | path exists)) { cs-prepend $sc_loc }
