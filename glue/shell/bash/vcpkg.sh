# vcpkg: export VCPKG_ROOT and put the `vcpkg` tool on PATH, from wherever configsys cloned it.
# CMake/toolchain integration reads VCPKG_ROOT. No-ops if vcpkg isn't installed.
_vp=$(configsys location vcpkg 2>/dev/null)
if [ -n "$_vp" ] && [ -x "$_vp/vcpkg" ]; then
    export VCPKG_ROOT="$_vp"
    case ":$PATH:" in *":$_vp:"*) ;; *) export PATH="$_vp:$PATH" ;; esac
fi
unset _vp
