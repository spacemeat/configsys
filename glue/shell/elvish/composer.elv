# composer: put its user-install bin dir(s) on PATH.
use path
if (and (path:is-dir $E:HOME/.config/composer/vendor/bin) (not (has-value $paths $E:HOME/.config/composer/vendor/bin))) {
  set paths = [$@paths $E:HOME/.config/composer/vendor/bin]
}
if (and (path:is-dir $E:HOME/.composer/vendor/bin) (not (has-value $paths $E:HOME/.composer/vendor/bin))) {
  set paths = [$@paths $E:HOME/.composer/vendor/bin]
}
