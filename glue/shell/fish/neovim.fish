# neovim: alias v/vi to the appImage wherever configsys installed it. No-ops where nvim is native.
set -l loc (cs_loc neovim)
if test -x "$loc"
    alias v "$loc"
    alias vi "$loc"
end
