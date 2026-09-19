# vcpkg: export VCPKG_ROOT + put the vcpkg tool on PATH (CMake reads VCPKG_ROOT).
let vcpkg_loc = (cs-loc vcpkg)
if (($vcpkg_loc != "") and ($"($vcpkg_loc)/vcpkg" | path exists)) { $env.VCPKG_ROOT = $vcpkg_loc; cs-prepend $vcpkg_loc }
