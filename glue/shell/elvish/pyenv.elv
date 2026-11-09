# pyenv: user-scope Python builds under ~/.pyenv — PYENV_ROOT + its bin and shims on PATH. The
# `pyenv` shell function (for `pyenv shell`) doesn't cross to elvish, but the shims resolve the
# selected python. No-op if pyenv isn't installed.
use path
if (path:is-dir $E:HOME/.pyenv/bin) {
  set E:PYENV_ROOT = $E:HOME/.pyenv
  for d [$E:PYENV_ROOT/bin $E:PYENV_ROOT/shims] {
    if (and (path:is-dir $d) (not (has-value $paths $d))) { set paths = [$d $@paths] }
  }
}
