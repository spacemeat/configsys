# vcpkg: export VCPKG_ROOT and put the `vcpkg` tool on PATH, from wherever configsys cloned it.
set -l loc (cs_loc vcpkg)
if test -n "$loc"; and test -x "$loc/vcpkg"
    set -gx VCPKG_ROOT "$loc"
    fish_add_path -g "$loc"
end
