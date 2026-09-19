# pyenv: user-scope Python builds under ~/.pyenv — PYENV_ROOT + the shims/bin on PATH (via the bash
# bridge, which also runs `pyenv init -`). The `pyenv` shell FUNCTION (for `pyenv shell`) doesn't cross
# to nu, but the shims resolve the selected python. No-op if pyenv isn't installed.
cs-bash-env 'export PYENV_ROOT="$HOME/.pyenv"; [ -d "$PYENV_ROOT/bin" ] && export PATH="$PYENV_ROOT/bin:$PATH"; command -v pyenv >/dev/null 2>&1 && eval "$(pyenv init -)"'
