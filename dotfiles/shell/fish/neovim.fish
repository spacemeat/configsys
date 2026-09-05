# neovim: alias v/vi to the appImage wherever configsys installed it. No-ops where nvim is native.
set -l loc (configsys location neovim 2>/dev/null)
if test -x "$loc"
    alias v "$loc"
    alias vi "$loc"
end
