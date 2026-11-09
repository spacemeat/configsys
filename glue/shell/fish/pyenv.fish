# pyenv: user-scope Python builds under ~/.pyenv; shims on PATH + shell hooks.
set -gx PYENV_ROOT "$HOME/.pyenv"
test -d "$PYENV_ROOT/bin"; and fish_add_path -g "$PYENV_ROOT/bin"
command -v pyenv >/dev/null 2>&1; and cs_cached pyenv-init-fish-norehash pyenv pyenv init - --no-rehash fish | source   # cached; no per-start rehash
