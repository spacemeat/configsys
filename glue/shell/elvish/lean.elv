# Lean 4 via elan (userland version manager): put ~/.elan/bin on PATH so lean/lake resolve.
use path
if (and (path:is-dir $E:HOME/.elan/bin) (not (has-value $paths $E:HOME/.elan/bin))) {
  set paths = [$E:HOME/.elan/bin $@paths]
}
