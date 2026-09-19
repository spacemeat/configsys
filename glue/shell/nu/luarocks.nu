# LuaRocks: --local rocks under ~/.luarocks — bin on PATH + LUA_PATH/LUA_CPATH (via `luarocks path`).
# No-op if luarocks isn't installed.
cs-bash-env '[ -d "$HOME/.luarocks/bin" ] && export PATH="$PATH:$HOME/.luarocks/bin"; command -v luarocks >/dev/null 2>&1 && eval "$(luarocks path 2>/dev/null)"'
