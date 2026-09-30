# LuaRocks: --local rocks under ~/.luarocks; bin on PATH + LUA_PATH/LUA_CPATH.
[ -d "$HOME/.luarocks/bin" ] && export PATH="$PATH:$HOME/.luarocks/bin"
# LUA_PATH/LUA_CPATH from luarocks, cached (re-run only after a luarocks upgrade). NOT `luarocks path`:
# that also bakes the whole current $PATH into an `export PATH=…`, which a cache would freeze.
if command -v luarocks >/dev/null 2>&1; then
    _lp=$(cs_cached luarocks-lr-path luarocks luarocks path --lr-path)
    _lc=$(cs_cached luarocks-lr-cpath luarocks luarocks path --lr-cpath)
    [ -n "$_lp" ] && export LUA_PATH="$_lp;;"
    [ -n "$_lc" ] && export LUA_CPATH="$_lc;;"
    unset _lp _lc
fi
