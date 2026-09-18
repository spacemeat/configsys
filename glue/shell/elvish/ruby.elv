# Ruby: user gems (bundler etc.) install to Gem.user_dir/bin (path varies), so query it.
use path
if (has-external ruby) {
  var gd = ''
  for _l [(ruby -e 'print Gem.user_dir' 2>/dev/null)] { set gd = $_l }
  if (and (not-eq $gd '') (path:is-dir $gd/bin) (not (has-value $paths $gd/bin))) { set paths = [$@paths $gd/bin] }
}
