# pyenv: user-scope Python builds under ~/.pyenv; shims on PATH + shell hooks.
export PYENV_ROOT="$HOME/.pyenv"
[ -d "$PYENV_ROOT/bin" ] && export PATH="$PYENV_ROOT/bin:$PATH"
command -v pyenv >/dev/null 2>&1 && eval "$(cs_cached pyenv-init-bash pyenv pyenv init - bash)"   # cached: re-runs only after a pyenv upgrade
