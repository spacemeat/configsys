# LuaRocks: --local rocks under ~/.luarocks; bin on PATH + LUA_PATH/LUA_CPATH. (`luarocks path`
# emits POSIX `export` lines fish can't eval, so query the individual paths instead.)
test -d "$HOME/.luarocks/bin"; and fish_add_path -ga "$HOME/.luarocks/bin"
if command -v luarocks >/dev/null 2>&1
    set -l lp (luarocks path --lr-path 2>/dev/null)
    set -l lc (luarocks path --lr-cpath 2>/dev/null)
    test -n "$lp"; and set -gx LUA_PATH "$lp;;"
    test -n "$lc"; and set -gx LUA_CPATH "$lc;;"
end
