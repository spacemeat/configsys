# neovim: alias v/vi to the appImage wherever configsys installed it. No-ops where nvim is
# native on PATH (location then reports no managed dir and this simply skips).
_nv=$(cs_loc neovim)
[ -x "$_nv" ] && { alias v="$_nv"; alias vi="$_nv"; }
unset _nv
