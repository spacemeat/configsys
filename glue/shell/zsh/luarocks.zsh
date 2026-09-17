# LuaRocks: --local rocks under ~/.luarocks; bin on PATH + LUA_PATH/LUA_CPATH.
[ -d "$HOME/.luarocks/bin" ] && export PATH="$PATH:$HOME/.luarocks/bin"
command -v luarocks >/dev/null 2>&1 && eval "$(luarocks path 2>/dev/null)"
