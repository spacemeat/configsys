# grpcurl: put the configsys-managed dir on PATH. No-op where native on PATH.
let grpcurl_loc = (cs-loc grpcurl)
if (($grpcurl_loc != "") and ($"($grpcurl_loc)/grpcurl" | path exists)) { cs-prepend $grpcurl_loc }
